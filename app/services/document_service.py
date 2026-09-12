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


async def process_and_store_document(
    workspace_id: str,
    user_id: str,
    file_name: str,
    file_bytes: bytes
) -> Dict[str, Any]:
    """
    Backend Document Ingestion Pipeline:
    Extracts text -> Chunks text -> Generates embeddings -> Stores chunks & pgvectors -> Updates document status.
    """
    await verify_workspace_member(user_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))
    doc_id = uuid.uuid4()
    file_type = file_name.split(".")[-1].upper() if "." in file_name else "UNKNOWN"
    file_size = len(file_bytes)

    # 1. Create document record in 'uploading' status
    insert_doc_query = """
        INSERT INTO documents (id, workspace_id, name, file_type, file_size, uploaded_by, status)
        VALUES ($1, $2, $3, $4, $5, $6, 'processing')
        RETURNING *
    """
    doc_record = await fetch_one(insert_doc_query, doc_id, ws_uuid, file_name, file_type, file_size, user_id)

    try:
        # 2. Extract text from file
        pages = extract_text_from_file(file_bytes, file_name)

        # 3. Chunk text
        await execute("UPDATE documents SET status = 'chunking' WHERE id = $1", doc_id)
        chunks = chunk_extracted_pages(pages)

        if not chunks:
            raise ValueError("No extractable text found in the document.")

        # 4. Generate embeddings
        await execute("UPDATE documents SET status = 'embedding' WHERE id = $1", doc_id)
        chunk_texts = [c["content"] for c in chunks]
        embeddings = generate_embeddings_batch(chunk_texts)

        # 5. Insert chunks + pgvectors into database
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

                # 6. Update document status to 'indexed'
                await conn.execute(
                    """
                    UPDATE documents
                    SET status = 'indexed', chunk_count = $1, error_message = NULL
                    WHERE id = $2
                    """,
                    len(chunks), doc_id
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
