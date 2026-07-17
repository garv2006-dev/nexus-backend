import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import schemas
from ..auth import get_current_user
from ..config import get_settings
from ..database import messages_collection, sessions_collection
from ..ids import gen_id
from ..services.ai_service import generate_reply_stream
from ..services.credits import ensure_and_consume_credit

router = APIRouter(prefix="/api/sessions", tags=["chat"])
settings = get_settings()


async def _get_owned_session(session_id: str, user_id: str) -> dict:
    session = await sessions_collection().find_one({"_id": session_id, "user_id": user_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _session_out(doc: dict) -> schemas.SessionOut:
    return schemas.SessionOut(id=doc["_id"], title=doc["title"], created_at=doc["created_at"])


def _message_out(doc: dict) -> schemas.MessageOut:
    return schemas.MessageOut(
        id=doc["_id"], role=doc["role"], content=doc["content"], created_at=doc["created_at"]
    )


@router.post("", response_model=schemas.SessionOut)
async def create_session(payload: schemas.SessionCreate, user: dict = Depends(get_current_user)):
    doc = {
        "_id": gen_id(),
        "user_id": user["_id"],
        "title": payload.title or "New chat",
        "created_at": datetime.now(timezone.utc),
    }
    await sessions_collection().insert_one(doc)
    return _session_out(doc)


@router.get("", response_model=list[schemas.SessionOut])
async def list_sessions(user: dict = Depends(get_current_user)):
    cursor = sessions_collection().find({"user_id": user["_id"]}).sort("created_at", -1)
    return [_session_out(doc) async for doc in cursor]


@router.get("/{session_id}", response_model=schemas.SessionDetailOut)
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    session = await _get_owned_session(session_id, user["_id"])
    cursor = messages_collection().find({"session_id": session_id}).sort("created_at", 1)
    messages = [_message_out(doc) async for doc in cursor]
    return schemas.SessionDetailOut(**_session_out(session).model_dump(), messages=messages)


@router.patch("/{session_id}", response_model=schemas.SessionOut)
async def rename_session(
    session_id: str, payload: schemas.SessionRename, user: dict = Depends(get_current_user)
):
    session = await _get_owned_session(session_id, user["_id"])
    await sessions_collection().update_one({"_id": session_id}, {"$set": {"title": payload.title}})
    session["title"] = payload.title
    return _session_out(session)


@router.delete("/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_session(session_id, user["_id"])
    await sessions_collection().delete_one({"_id": session_id})
    await messages_collection().delete_many({"session_id": session_id})
    return {"ok": True}


@router.post("/{session_id}/messages")
async def send_message(
    session_id: str, payload: schemas.MessageCreate, user: dict = Depends(get_current_user)
):
    session = await _get_owned_session(session_id, user["_id"])

    # Check + deduct credits before doing any (paid) AI work.
    await ensure_and_consume_credit(user)

    now = datetime.now(timezone.utc)
    user_message = {
        "_id": gen_id(),
        "session_id": session_id,
        "user_id": user["_id"],
        "role": "user",
        "content": payload.content,
        "created_at": now,
    }
    await messages_collection().insert_one(user_message)

    if session["title"] == "New chat":
        trimmed = payload.content.strip().splitlines()[0][:40]
        new_title = trimmed + ("..." if len(payload.content.strip()) > 40 else "")
        await sessions_collection().update_one(
            {"_id": session_id}, {"$set": {"title": new_title}}
        )

    history_cursor = messages_collection().find({"session_id": session_id}).sort("created_at", 1)
    history = [{"role": doc["role"], "content": doc["content"]} async for doc in history_cursor]

    async def event_stream():
        full_reply = ""
        try:
            async for chunk in generate_reply_stream(settings.ai_provider, history):
                full_reply += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            assistant_message = {
                "_id": gen_id(),
                "session_id": session_id,
                "user_id": user["_id"],
                "role": "assistant",
                "content": full_reply,
                "created_at": datetime.now(timezone.utc),
            }
            await messages_collection().insert_one(assistant_message)

            yield (
                "data: "
                f"{json.dumps({'type': 'done', 'message_id': assistant_message['_id'], 'credits': user['credits']})}"
                "\n\n"
            )
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
