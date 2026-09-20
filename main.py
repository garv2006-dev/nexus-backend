from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_pool, close_pool
from app.routers import workspaces, invitations, documents, rag, usage, users, payments

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
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS max_pages INT NOT NULL DEFAULT 25;")
        await execute("ALTER TABLE workspaces ALTER COLUMN max_pages SET DEFAULT 25;")
        await execute("ALTER TABLE workspaces ALTER COLUMN daily_token_limit SET DEFAULT 25000;")
        await execute("ALTER TABLE workspaces ALTER COLUMN max_members SET DEFAULT 3;")
        await execute("UPDATE workspaces SET daily_token_limit = 25000, max_pages = 25, max_members = 3 WHERE plan_type = 'starter' OR plan_type IS NULL;")
        await execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INT DEFAULT 1;")
        
        # User schema extensions
        await execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;")
        await execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;")
        await execute("UPDATE users SET name = 'Garv Variya', first_name = 'Garv', last_name = 'Variya' WHERE (email ILIKE '%garvvariya03%' OR name ILIKE '%garvvariya03%') AND (first_name IS NULL OR first_name = '');")
        await execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;")
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;")
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;")
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS subscription_status TEXT DEFAULT 'active';")
        await execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;")

        await execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id TEXT NOT NULL,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                stripe_customer_id TEXT,
                stripe_checkout_session_id TEXT UNIQUE,
                stripe_payment_intent_id TEXT,
                stripe_subscription_id TEXT,
                plan_id TEXT NOT NULL,
                amount INT NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'usd',
                payment_status TEXT NOT NULL DEFAULT 'pending',
                subscription_status TEXT NOT NULL DEFAULT 'incomplete',
                created_at TIMESTAMPTZ DEFAULT now(),
                completed_at TIMESTAMPTZ,
                canceled_at TIMESTAMPTZ
            );
        """)
        await execute("CREATE INDEX IF NOT EXISTS idx_payments_workspace ON payments(workspace_id);")
        await execute("CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);")
        await execute("CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(stripe_checkout_session_id);")
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
app.include_router(payments.router)



@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Multi-User RAG Workspace System"
    }
