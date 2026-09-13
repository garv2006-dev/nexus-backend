import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..database import fetch_one, fetch_all, execute
from ..services.workspace_service import verify_workspace_member
from ..services.rag_service import execute_rag_query

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["conversations_and_rag"])


class ConversationCreatePayload(BaseModel):
    title: Optional[str] = "New Chat"


class ChatQueryPayload(BaseModel):
    conversation_id: str
    query: str = Field(..., min_length=1, max_length=4000, description="User question query string (1 to 4000 characters)")


@router.get("/conversations", response_model=List[dict])
async def list_conversations(workspace_id: str, user: dict = Depends(get_current_user)):
    await verify_workspace_member(user["id"], workspace_id)
    query = """
        SELECT id, workspace_id, user_id, title, created_at, updated_at
        FROM conversations
        WHERE workspace_id = $1 AND user_id = $2
        ORDER BY updated_at DESC
    """
    return await fetch_all(query, uuid.UUID(str(workspace_id)), user["id"])


@router.post("/conversations", response_model=dict)
async def create_conversation(
    workspace_id: str,
    payload: ConversationCreatePayload,
    user: dict = Depends(get_current_user)
):
    await verify_workspace_member(user["id"], workspace_id)
    conv_id = uuid.uuid4()
    ws_uuid = uuid.UUID(str(workspace_id))
    title = payload.title or "New Chat"

    query = """
        INSERT INTO conversations (id, workspace_id, user_id, title)
        VALUES ($1, $2, $3, $4)
        RETURNING *
    """
    record = await fetch_one(query, conv_id, ws_uuid, user["id"], title)
    return dict(record)


@router.get("/conversations/{conversation_id}", response_model=dict)
async def get_conversation(
    workspace_id: str,
    conversation_id: str,
    user: dict = Depends(get_current_user)
):
    await verify_workspace_member(user["id"], workspace_id)
    conv_uuid = uuid.UUID(str(conversation_id))
    ws_uuid = uuid.UUID(str(workspace_id))

    conv = await fetch_one(
        "SELECT * FROM conversations WHERE id = $1 AND workspace_id = $2 AND user_id = $3",
        conv_uuid, ws_uuid, user["id"]
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    messages_query = """
        SELECT id, conversation_id, role, content, sources, token_usage, created_at
        FROM messages
        WHERE conversation_id = $1
        ORDER BY created_at ASC
    """
    messages = await fetch_all(messages_query, conv_uuid)

    return {
        **dict(conv),
        "messages": messages
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    workspace_id: str,
    conversation_id: str,
    user: dict = Depends(get_current_user)
):
    await verify_workspace_member(user["id"], workspace_id)
    conv_uuid = uuid.UUID(str(conversation_id))
    ws_uuid = uuid.UUID(str(workspace_id))

    await execute(
        "DELETE FROM conversations WHERE id = $1 AND workspace_id = $2 AND user_id = $3",
        conv_uuid, ws_uuid, user["id"]
    )
    return {"status": "deleted", "conversation_id": conversation_id}


@router.post("/chat", response_model=dict)
async def chat_rag_endpoint(
    workspace_id: str,
    payload: ChatQueryPayload,
    user: dict = Depends(get_current_user)
):
    """
    RAG Chat endpoint:
    Executes hybrid search vector retrieval, validates workspace daily token limits,
    generates grounded answer from Gemini LLM, updates token counter, and returns response with citations.
    """
    return await execute_rag_query(
        workspace_id=workspace_id,
        user_id=user["id"],
        conversation_id=payload.conversation_id,
        query_text=payload.query
    )
