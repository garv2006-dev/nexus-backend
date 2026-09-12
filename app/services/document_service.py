import uuid
from typing import Dict, List, Any
from fastapi import HTTPException
from ..database import fetch_one, fetch_all, execute, get_pool
from .workspace_service import verify_workspace_member
from .ingestion_service import extract_text_from_file, chunk_extracted_pages
from .embedding_service import generate_embeddings_batch


async def list_workspace_documents(workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Lists all uploaded documents in the specified workspace."""
    await verify_workspace_member(user_id, workspace_id)
    query = """
        SELECT 
            d.id,
            d.workspace_id,
            d.name,
            d.file_type,
            d.file_size,
            COALESCE(d.page_count, 1) as page_count,
            d.chunk_count,
            d.status,
            d.error_message,
            d.created_at,
            u.name as uploader_name,
            u.email as uploader_email
        FROM documents d
        JOIN users u ON u.id = d.uploaded_by
        WHERE d.workspace_id = $1
        ORDER BY d.created_at DESC
    """
    return await fetch_all(query, uuid.UUID(str(workspace_id)))


async def verify_document_upload_permission_and_limit(workspace_id: str, user_id: str, incoming_count: int = 1):
    """Verifies that user is owner or admin AND workspace has available page capacity within max_pages limit."""
    member = await verify_workspace_member(user_id, workspace_id)
    role = member.get("role") or member.get("user_role") or "member"
    if role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Only Workspace Owners and Admins are permitted to add/upload documents."
        )

    ws_uuid = uuid.UUID(str(workspace_id))
    ws_info = await fetch_one("SELECT COALESCE(max_pages, 50) as max_pages FROM workspaces WHERE id = $1", ws_uuid)
    max_pages = ws_info.get("max_pages", 50) if ws_info else 50

    from ..database import fetch_val
    curr_pages = await fetch_val("SELECT COALESCE(SUM(page_count), 0) FROM documents WHERE workspace_id = $1", ws_uuid) or 0
    if curr_pages >= max_pages:
        raise HTTPException(
            status_code=400,
            detail=f"Workspace page capacity limit reached ({curr_pages}/{max_pages} pages used, 0 pages space available). Please upgrade your workspace plan to upload more pages."
        )


async def process_and_store_document(
    workspace_id: str,
    user_id: str,
    file_name: str,
    file_bytes: bytes
) -> Dict[str, Any]:
    """
    Backend Document Ingestion Pipeline:
    Extracts text -> Checks page capacity -> Chunks text -> Generates embeddings -> Stores chunks & pgvectors in Vector Store.
    """
    await verify_document_upload_permission_and_limit(workspace_id, user_id, 1)
    ws_uuid = uuid.UUID(str(workspace_id))
    doc_id = uuid.uuid4()
    file_type = file_name.split(".")[-1].upper() if "." in file_name else "UNKNOWN"
    file_size = len(file_bytes)

    # 1. Create document record in 'processing' status
    insert_doc_query = """
        INSERT INTO documents (id, workspace_id, name, file_type, file_size, uploaded_by, status)
        VALUES ($1, $2, $3, $4, $5, $6, 'processing')
        RETURNING *
    """
    doc_record = await fetch_one(insert_doc_query, doc_id, ws_uuid, file_name, file_type, file_size, user_id)

    try:
        # 2. Extract text from file and inspect page count
        pages = extract_text_from_file(file_bytes, file_name)
        num_pages = len(pages)

        # Enforce available page space limit for this workspace
        ws_info = await fetch_one("SELECT COALESCE(max_pages, 50) as max_pages FROM workspaces WHERE id = $1", ws_uuid)
        max_pages = ws_info.get("max_pages", 50) if ws_info else 50

        from ..database import fetch_val
        used_pages = await fetch_val("SELECT COALESCE(SUM(page_count), 0) FROM documents WHERE workspace_id = $1 AND id != $2", ws_uuid, doc_id) or 0
        avail_pages = max_pages - used_pages

        if num_pages > avail_pages:
            raise ValueError(
                f"Document rejected: '{file_name}' contains {num_pages} pages, but only {avail_pages} pages space available ({used_pages}/{max_pages} pages used). Upgrade workspace plan to process larger documents."
            )

        # 3. Chunk text & update page_count
        await execute("UPDATE documents SET status = 'chunking', page_count = $1 WHERE id = $2", num_pages, doc_id)
        chunks = chunk_extracted_pages(pages)

        if not chunks:
            raise ValueError("No extractable text found in the document.")

        # 4. Generate embeddings
        await execute("UPDATE documents SET status = 'embedding' WHERE id = $1", doc_id)
        chunk_texts = [c["content"] for c in chunks]
        embeddings = generate_embeddings_batch(chunk_texts)

        # 5. Insert chunks + pgvectors into vector store database
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for c, emb in zip(chunks, embeddings):
                    chunk_id = uuid.uuid4()
                    c_idx = c["chunk_index"]
                    p_num = c["page_number"]
                    content = c["content"]

                    # Format embedding vector for pgvector input (e.g. '[0.1, 0.2, ...]')
                    vec_str = "[" + ",".join(str(f) for f in emb) + "]"

                    await conn.execute(
                        """
                        INSERT INTO document_chunks (id, workspace_id, document_id, content, embedding, chunk_index, page_number)
                        VALUES ($1, $2, $3, $4, $5::vector, $6, $7)
                        """,
                        chunk_id, ws_uuid, doc_id, content, vec_str, c_idx, p_num
                    )

                # 6. Update document status to 'indexed' and save page_count
                await conn.execute(
                    """
                    UPDATE documents
                    SET status = 'indexed', chunk_count = $1, page_count = $2, error_message = NULL
                    WHERE id = $3
                    """,
                    len(chunks), num_pages, doc_id
                )

        updated_doc = await fetch_one("SELECT * FROM documents WHERE id = $1", doc_id)
        return updated_doc

    except Exception as exc:
        err_msg = str(exc)[:500]
        await execute(
            "UPDATE documents SET status = 'failed', error_message = $1 WHERE id = $2",
            err_msg, doc_id
        )
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed for '{file_name}': {err_msg}"
        )


async def delete_document(workspace_id: str, user_id: str, document_id: str) -> bool:
    """Deletes document metadata and all associated chunks & embeddings (cascading)."""
    await verify_workspace_member(user_id, workspace_id)
    doc_uuid = uuid.UUID(str(document_id))
    ws_uuid = uuid.UUID(str(workspace_id))

    doc = await fetch_one("SELECT * FROM documents WHERE id = $1 AND workspace_id = $2", doc_uuid, ws_uuid)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in this workspace.")

    # ON DELETE CASCADE handles document_chunks and embeddings
    await execute("DELETE FROM documents WHERE id = $1", doc_uuid)
    return True
