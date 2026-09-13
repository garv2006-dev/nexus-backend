from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_pool, close_pool
from app.routers import workspaces, invitations, documents, rag, usage, users

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up Multi-User RAG API server...")
    pool = await init_pool()
    try:
        from app.database import execute
        await execute("ALTER TABLE workspace_invitations ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'member';")
        await execute("ALTER TABLE workspace_members DROP CONSTRAINT IF EXISTS workspace_members_role_check;")
        await execute("ALTER TABLE workspace_members ADD CONSTRAINT workspace_members_role_check CHECK (role IN ('owner', 'admin', 'member'));")
        await execute("ALTER TABLE workspace_invitations DROP CONSTRAINT IF EXISTS workspace_invitations_role_check;")
        await execute("ALTER TABLE workspace_invitations ADD CONSTRAINT workspace_invitations_role_check CHECK (role IN ('owner', 'admin', 'member'));")
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS plan_type TEXT NOT NULL DEFAULT 'starter';")
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS max_pages INT NOT NULL DEFAULT 50;")
        await execute("ALTER TABLE workspaces ALTER COLUMN max_pages SET DEFAULT 50;")
        await execute("ALTER TABLE workspaces ALTER COLUMN daily_token_limit SET DEFAULT 50000;")
        await execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INT DEFAULT 1;")
    except Exception as err:
        print(f"Schema migration warning: {err}")
    yield
    print("Shutting down Multi-User RAG API server...")
    await close_pool()


app = FastAPI(
    title="Production-Ready Multi-User RAG Workspace API",
    version="3.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(invitations.router)
app.include_router(documents.router)
app.include_router(rag.router)
app.include_router(usage.router)
app.include_router(users.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Multi-User RAG Workspace System"
    }
