import uuid
from datetime import date
from typing import Dict, List, Any
from fastapi import HTTPException
from ..database import fetch_one, fetch_all, execute
from .workspace_service import verify_workspace_member


async def get_workspace_today_usage(workspace_id: str, user_id: str) -> Dict[str, Any]:
    """Returns today's token usage, daily limit, and remaining budget for the workspace."""
    await verify_workspace_member(user_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))

    ws = await fetch_one("SELECT daily_token_limit FROM workspaces WHERE id = $1", ws_uuid)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    daily_limit = ws["daily_token_limit"]

    usage_row = await fetch_one(
        "SELECT input_tokens, output_tokens, total_tokens FROM usage WHERE workspace_id = $1 AND usage_date = CURRENT_DATE",
        ws_uuid
    )

    input_tokens = usage_row["input_tokens"] if usage_row else 0
    output_tokens = usage_row["output_tokens"] if usage_row else 0
    total_tokens = usage_row["total_tokens"] if usage_row else 0
    remaining = max(0, daily_limit - total_tokens)

    return {
        "workspace_id": str(workspace_id),
        "usage_date": str(date.today()),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "daily_limit": daily_limit,
        "remaining_tokens": remaining,
        "is_limit_reached": total_tokens >= daily_limit
    }


async def check_daily_token_budget(workspace_id: str, estimated_tokens: int = 1000) -> None:
    """Pre-flight check before making LLM calls. Raises 429 if budget is exceeded."""
    ws_uuid = uuid.UUID(str(workspace_id))
    ws = await fetch_one("SELECT daily_token_limit FROM workspaces WHERE id = $1", ws_uuid)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    daily_limit = ws["daily_token_limit"]
    usage_row = await fetch_one(
        "SELECT total_tokens FROM usage WHERE workspace_id = $1 AND usage_date = CURRENT_DATE",
        ws_uuid
    )
    current_total = usage_row["total_tokens"] if usage_row else 0

    if current_total + estimated_tokens > daily_limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily workspace token limit reached. Used: {current_total:,} / {daily_limit:,} tokens."
        )


async def record_token_usage(workspace_id: str, input_tokens: int, output_tokens: int) -> Dict[str, Any]:
    """Atomically updates workspace token usage for today."""
    ws_uuid = uuid.UUID(str(workspace_id))
    total_tokens = input_tokens + output_tokens

    query = """
        INSERT INTO usage (workspace_id, usage_date, input_tokens, output_tokens, total_tokens)
        VALUES ($1, CURRENT_DATE, $2, $3, $4)
        ON CONFLICT (workspace_id, usage_date)
        DO UPDATE SET
            input_tokens = usage.input_tokens + EXCLUDED.input_tokens,
            output_tokens = usage.output_tokens + EXCLUDED.output_tokens,
            total_tokens = usage.total_tokens + EXCLUDED.total_tokens
        RETURNING *
    """
    row = await fetch_one(query, ws_uuid, input_tokens, output_tokens, total_tokens)
    return dict(row) if row else {}


async def get_usage_history(workspace_id: str, user_id: str, days: int = 14) -> List[Dict[str, Any]]:
    """Returns historical daily token usage breakdown."""
    await verify_workspace_member(user_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))

    query = """
        SELECT 
            TO_CHAR(usage_date, 'YYYY-MM-DD') as date_str,
            input_tokens,
            output_tokens,
            total_tokens
        FROM usage
        WHERE workspace_id = $1
        ORDER BY usage_date DESC
        LIMIT $2
    """
    rows = await fetch_all(query, ws_uuid, days)
    return rows
