from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_client, get_database
from app.routers import chat, users

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_database()
    # Helpful indexes; safe to call on every startup (no-op if they exist).
    await db["chat_sessions"].create_index([("user_id", 1), ("created_at", -1)])
    await db["chat_messages"].create_index([("session_id", 1), ("created_at", 1)])
    yield
    close_client()


app = FastAPI(title="Nexus AI Chat API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(users.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "provider": settings.ai_provider}

# trigger reload
