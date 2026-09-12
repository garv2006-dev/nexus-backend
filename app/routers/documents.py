from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from ..auth import get_current_user
from ..config import get_settings
from ..services import document_service

settings = get_settings()
router = APIRouter(prefix="/api/workspaces/{workspace_id}/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}


@router.get("", response_model=List[dict])
async def list_documents(workspace_id: str, user: dict = Depends(get_current_user)):
    return await document_service.list_workspace_documents(workspace_id, user["id"])


@router.post("/upload", response_model=List[dict])
async def upload_documents(
    workspace_id: str,
    files: List[UploadFile] = File(...),
    user: dict = Depends(get_current_user)
):
    """
    Multiple file upload endpoint supporting PDF, DOC, and DOCX files.
    Processes each file through text extraction, chunking, embedding, and storage.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    results = []

    for file in files:
        file_name = file.filename or "file.pdf"
        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Allowed formats: PDF, DOC, DOCX."
            )

        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file_name}' exceeds maximum limit of {settings.max_file_size_mb}MB."
            )

        doc_record = await document_service.process_and_store_document(
            workspace_id=workspace_id,
            user_id=user["id"],
            file_name=file_name,
            file_bytes=content
        )
        results.append(doc_record)

    return results


@router.delete("/{document_id}")
async def delete_document(
    workspace_id: str,
    document_id: str,
    user: dict = Depends(get_current_user)
):
    await document_service.delete_document(workspace_id, user["id"], document_id)
    return {"status": "deleted", "document_id": document_id}
