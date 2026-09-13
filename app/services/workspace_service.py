import uuid
from typing import Dict, List, Any
from fastapi import HTTPException
from ..database import fetch_one, fetch_all, fetch_val, execute, get_pool


async def verify_workspace_member(user_id: str, workspace_id: str) -> Dict[str, Any]:
    """Verifies that the user is a member or owner of the specified workspace."""
    query = """
        SELECT wm.*, w.name as workspace_name, w.owner_id
        FROM workspace_members wm
        JOIN workspaces w ON w.id = wm.workspace_id
        WHERE wm.workspace_id = $1 AND wm.user_id = $2
    """
    member = await fetch_one(query, uuid.UUID(str(workspace_id)), user_id)
    if not member:
        raise HTTPException(
            status_code=403,
            detail="Access denied: You are not a member of this workspace."
        )
    return member


async def verify_workspace_owner(user_id: str, workspace_id: str) -> Dict[str, Any]:
    """Verifies that the user is the owner of the specified workspace."""
    query = "SELECT * FROM workspaces WHERE id = $1"
    ws = await fetch_one(query, uuid.UUID(str(workspace_id)))
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if str(ws["owner_id"]) != str(user_id):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Only the workspace owner can perform this operation."
        )
    return ws


async def verify_workspace_admin_or_owner(user_id: str, workspace_id: str) -> Dict[str, Any]:
    """Verifies that the user is an owner or admin of the specified workspace."""
    member = await verify_workspace_member(user_id, workspace_id)
    if member.get("role") not in ("owner", "admin") and str(member.get("owner_id")) != str(user_id):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Only workspace owners and admins can perform this operation."
        )
    return member


PLAN_SPECS = {
    "starter": {"daily_token_limit": 25000, "max_pages": 25, "max_members": 3},
    "pro": {"daily_token_limit": 250000, "max_pages": 100, "max_members": 10},
    "enterprise": {"daily_token_limit": 1000000, "max_pages": 150, "max_members": 25},
}


async def create_workspace(user_id: str, name: str) -> Dict[str, Any]:
    """Creates a new workspace with automatic default starter plan."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ws_id = uuid.uuid4()
            ws_query = """
                INSERT INTO workspaces (id, name, owner_id, plan_type, daily_token_limit, max_pages, max_members)
                VALUES ($1, $2, $3, 'starter', 25000, 25, 3)
                RETURNING *
            """
            ws_record = await conn.fetchrow(ws_query, ws_id, name, user_id)

            member_query = """
                INSERT INTO workspace_members (workspace_id, user_id, role)
                VALUES ($1, $2, 'owner')
            """
            await conn.execute(member_query, ws_id, user_id)
            res = dict(ws_record)
            res["id"] = str(res["id"])
            res["owner_id"] = str(res["owner_id"])
            return res


async def list_user_workspaces(user_id: str) -> List[Dict[str, Any]]:
    """Lists all workspaces accessible to the user along with plan details, member & document/page counts."""
    query = """
        SELECT 
            w.id,
            w.name,
            w.owner_id,
            COALESCE(w.plan_type, 'starter') as plan_type,
            w.max_members,
            w.daily_token_limit,
            COALESCE(w.max_pages, 25) as max_pages,
            w.created_at,
            w.updated_at,
            wm.role as user_role,
            COALESCE(mc.member_count, 0) as member_count,
            COALESCE(dc.doc_count, 0) as document_count,
            COALESCE(dc.total_pages, 0) as page_count
        FROM workspace_members wm
        JOIN workspaces w ON w.id = wm.workspace_id
        LEFT JOIN (
            SELECT workspace_id, COUNT(*) as member_count
            FROM workspace_members
            GROUP BY workspace_id
        ) mc ON mc.workspace_id = w.id
        LEFT JOIN (
            SELECT workspace_id, COUNT(*) as doc_count, COALESCE(SUM(page_count), 0) as total_pages
            FROM documents
            GROUP BY workspace_id
        ) dc ON dc.workspace_id = w.id
        WHERE wm.user_id = $1
        ORDER BY w.created_at DESC
    """
    rows = await fetch_all(query, user_id)
    result = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["owner_id"] = str(item["owner_id"])
        result.append(item)
    return result


async def get_workspace_details(workspace_id: str, user_id: str) -> Dict[str, Any]:
    """Gets details for a specific workspace after verifying membership."""
    await verify_workspace_member(user_id, workspace_id)
    query = """
        SELECT 
            w.id,
            w.name,
            w.owner_id,
            COALESCE(w.plan_type, 'starter') as plan_type,
            w.max_members,
            w.daily_token_limit,
            COALESCE(w.max_pages, 25) as max_pages,
            w.created_at,
            w.updated_at,
            COALESCE(mc.member_count, 0) as member_count,
            COALESCE(dc.doc_count, 0) as document_count,
            COALESCE(dc.total_pages, 0) as page_count
        FROM workspaces w
        LEFT JOIN (
            SELECT workspace_id, COUNT(*) as member_count
            FROM workspace_members
            GROUP BY workspace_id
        ) mc ON mc.workspace_id = w.id
        LEFT JOIN (
            SELECT workspace_id, COUNT(*) as doc_count, COALESCE(SUM(page_count), 0) as total_pages
            FROM documents
            GROUP BY workspace_id
        ) dc ON dc.workspace_id = w.id
        WHERE w.id = $1
    """
    ws = await fetch_one(query, uuid.UUID(str(workspace_id)))
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    res = dict(ws)
    res["id"] = str(res["id"])
    res["owner_id"] = str(res["owner_id"])
    return res


async def update_workspace_settings(
    workspace_id: str,
    user_id: str,
    name: str = None,
    plan_type: str = None,
    max_members: int = None,
    daily_token_limit: int = None,
    max_pages: int = None
) -> Dict[str, Any]:
    """Updates workspace administrative settings and plan tier (owner or admin)."""
    await verify_workspace_admin_or_owner(user_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))

    updates = []
    params = [ws_uuid]

    if name is not None:
        params.append(name.strip())
        updates.append(f"name = ${len(params)}")

    if plan_type is not None and plan_type.lower() in PLAN_SPECS:
        clean_plan = plan_type.lower()
        spec = PLAN_SPECS[clean_plan]
        params.append(clean_plan)
        updates.append(f"plan_type = ${len(params)}")

        params.append(spec["daily_token_limit"])
        updates.append(f"daily_token_limit = ${len(params)}")

        params.append(spec["max_pages"])
        updates.append(f"max_pages = ${len(params)}")

        params.append(spec["max_members"])
        updates.append(f"max_members = ${len(params)}")
    else:
        if max_members is not None:
            params.append(max_members)
            updates.append(f"max_members = ${len(params)}")

        if daily_token_limit is not None:
            params.append(daily_token_limit)
            updates.append(f"daily_token_limit = ${len(params)}")

        if max_pages is not None:
            params.append(max_pages)
            updates.append(f"max_pages = ${len(params)}")

    if not updates:
        return await get_workspace_details(workspace_id, user_id)

    query = f"""
        UPDATE workspaces
        SET {', '.join(updates)}, updated_at = now()
        WHERE id = $1
        RETURNING *
    """
    record = await fetch_one(query, *params)
    res = dict(record)
    res["id"] = str(res["id"])
    res["owner_id"] = str(res["owner_id"])
    return res


async def delete_workspace(workspace_id: str, user_id: str) -> bool:
    """Deletes workspace and all associated records in cascading fashion (owner only)."""
    await verify_workspace_owner(user_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))
    
    # ON DELETE CASCADE handles document_chunks, documents, workspace_members, invitations, conversations, messages, usage
    await execute("DELETE FROM workspaces WHERE id = $1", ws_uuid)
    return True
