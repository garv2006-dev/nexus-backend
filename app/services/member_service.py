import uuid
from typing import Dict, List, Any
from fastapi import HTTPException
from ..database import fetch_one, fetch_all, fetch_val, execute, get_pool
from ..config import get_settings
from .workspace_service import verify_workspace_member, verify_workspace_owner
from .email_service import send_workspace_invitation_email


async def list_workspace_members(workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Lists all members in the workspace after verifying authorization."""
    await verify_workspace_member(user_id, workspace_id)
    query = """
        SELECT 
            wm.id,
            wm.workspace_id,
            wm.user_id,
            wm.role,
            wm.joined_at,
            u.email,
            COALESCE(
                NULLIF(
                    CASE WHEN u.name ILIKE 'User user_%' THEN '' ELSE u.name END, 
                    ''
                ),
                INITCAP(REPLACE(REPLACE(SPLIT_PART(u.email, '@', 1), '.', ' '), '_', ' ')),
                'Workspace Member'
            ) as name,
            u.avatar_url
        FROM workspace_members wm
        JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id = $1
        ORDER BY CASE WHEN wm.role = 'owner' THEN 0 WHEN wm.role = 'admin' THEN 1 ELSE 2 END, wm.joined_at ASC
    """
    rows = await fetch_all(query, uuid.UUID(str(workspace_id)))
    res = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["workspace_id"] = str(item["workspace_id"])
        res.append(item)
    return res


async def invite_member(workspace_id: str, inviter_id: str, target_email: str, role: str = "member") -> Dict[str, Any]:
    """Sends an invitation to join the workspace with a specified role after checking limits."""
    ws = await verify_workspace_owner(inviter_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))
    email_clean = target_email.strip().lower()
    target_role = role if role in ("owner", "admin", "member") else "member"

    # 1. Check member count limit
    current_count = await fetch_val(
        "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1",
        ws_uuid
    )
    max_members = ws["max_members"]

    if current_count >= max_members:
        raise HTTPException(
            status_code=400,
            detail="Workspace member limit reached."
        )

    # 2. Check if already a member
    existing_member = await fetch_one(
        """
        SELECT wm.* FROM workspace_members wm
        JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id = $1 AND LOWER(u.email) = $2
        """,
        ws_uuid, email_clean
    )
    if existing_member:
        raise HTTPException(status_code=400, detail="User is already a member of this workspace.")

    # 3. Fetch inviter details for email messaging
    inviter = await fetch_one("SELECT name, email FROM users WHERE id = $1", inviter_id)
    inviter_name = inviter["name"] if (inviter and inviter.get("name")) else (inviter["email"] if inviter else "A team member")

    # 4. Create pending invitation with specified role
    query = """
        INSERT INTO workspace_invitations (workspace_id, email, invited_by, role, status)
        VALUES ($1, $2, $3, $4, 'pending')
        RETURNING *
    """
    invitation = await fetch_one(query, ws_uuid, email_clean, inviter_id, target_role)

    # 5. Dispatch invitation email via Resend / Email Service
    settings = get_settings()
    invitation_url = f"{settings.app_frontend_url.rstrip('/')}/invitations"
    await send_workspace_invitation_email(
        to_email=email_clean,
        inviter_name=inviter_name,
        workspace_name=ws["name"],
        invitation_url=invitation_url
    )

    res = dict(invitation)
    res["id"] = str(res["id"])
    res["workspace_id"] = str(res["workspace_id"])
    return res


async def list_workspace_pending_invitations(workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Lists pending invitations sent for a specific workspace (members page view)."""
    await verify_workspace_member(user_id, workspace_id)
    query = """
        SELECT 
            wi.id,
            wi.workspace_id,
            wi.email,
            wi.role,
            wi.status,
            wi.created_at,
            u.name as inviter_name,
            u.email as inviter_email
        FROM workspace_invitations wi
        JOIN users u ON u.id = wi.invited_by
        WHERE wi.workspace_id = $1 AND wi.status = 'pending'
        ORDER BY wi.created_at DESC
    """
    rows = await fetch_all(query, uuid.UUID(str(workspace_id)))
    res = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["workspace_id"] = str(item["workspace_id"])
        res.append(item)
    return res


async def cancel_workspace_invitation(workspace_id: str, owner_id: str, invitation_id: str) -> bool:
    """Cancels/revokes a pending workspace invitation (owner only)."""
    await verify_workspace_owner(owner_id, workspace_id)
    ws_uuid = uuid.UUID(str(workspace_id))
    inv_uuid = uuid.UUID(str(invitation_id))

    await execute(
        "DELETE FROM workspace_invitations WHERE id = $1 AND workspace_id = $2",
        inv_uuid, ws_uuid
    )
    return True


async def list_pending_invitations_for_user(user_email: str) -> List[Dict[str, Any]]:
    """Lists pending workspace invitations for the specified user email."""
    if not user_email:
        return []
    query = """
        SELECT 
            wi.id,
            wi.workspace_id,
            wi.email,
            wi.role,
            wi.status,
            wi.created_at,
            w.name as workspace_name,
            u.name as inviter_name,
            u.email as inviter_email
        FROM workspace_invitations wi
        JOIN workspaces w ON w.id = wi.workspace_id
        JOIN users u ON u.id = wi.invited_by
        WHERE LOWER(wi.email) = LOWER($1) AND wi.status = 'pending'
        ORDER BY wi.created_at DESC
    """
    rows = await fetch_all(query, user_email.strip().lower())
    res = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["workspace_id"] = str(item["workspace_id"])
        res.append(item)
    return res


async def accept_invitation(invitation_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Accepts a pending invitation and adds the user to the workspace with the invited role."""
    inv_uuid = uuid.UUID(str(invitation_id))
    inv = await fetch_one("SELECT * FROM workspace_invitations WHERE id = $1", inv_uuid)
    
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    
    if inv["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Invitation has already been {inv['status']}.")

    user_email = (user.get("email") or "").strip().lower()
    if inv["email"].strip().lower() != user_email:
        raise HTTPException(status_code=403, detail="This invitation was sent to a different email address.")

    ws_uuid = inv["workspace_id"]
    invited_role = inv.get("role") or "member"
    ws = await fetch_one("SELECT * FROM workspaces WHERE id = $1", ws_uuid)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace no longer exists.")

    # Re-verify capacity
    current_count = await fetch_val(
        "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1",
        ws_uuid
    )
    if current_count >= ws["max_members"]:
        raise HTTPException(status_code=400, detail="Workspace member limit reached.")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Add member with the invited role
            await conn.execute(
                """
                INSERT INTO workspace_members (workspace_id, user_id, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                ws_uuid, user["id"], invited_role
            )
            # Update invitation status
            await conn.execute(
                "UPDATE workspace_invitations SET status = 'accepted' WHERE id = $1",
                inv_uuid
            )

    return {"status": "accepted", "workspace_id": str(ws_uuid), "role": invited_role}


async def reject_invitation(invitation_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Rejects a pending invitation."""
    inv_uuid = uuid.UUID(str(invitation_id))
    inv = await fetch_one("SELECT * FROM workspace_invitations WHERE id = $1", inv_uuid)
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found.")

    user_email = (user.get("email") or "").strip().lower()
    if inv["email"].strip().lower() != user_email:
        raise HTTPException(status_code=403, detail="This invitation was sent to a different email address.")

    await execute("UPDATE workspace_invitations SET status = 'rejected' WHERE id = $1", inv_uuid)
    return {"status": "rejected"}


async def remove_member(workspace_id: str, owner_id: str, member_user_id: str) -> bool:
    """Removes a member from the workspace (owner only)."""
    ws = await verify_workspace_owner(owner_id, workspace_id)
    if str(ws["owner_id"]) == str(member_user_id):
        raise HTTPException(status_code=400, detail="Cannot remove the workspace owner.")

    await execute(
        "DELETE FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
        uuid.UUID(str(workspace_id)), member_user_id
    )
    return True
