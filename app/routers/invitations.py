from typing import List, Optional
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, EmailStr

from ..auth import get_current_user
from ..services import member_service

router = APIRouter(tags=["invitations_and_members"])


class InvitePayload(BaseModel):
    email: EmailStr
    role: str = "member"  # 'owner', 'admin', 'member'
    inviter_name: Optional[str] = None


@router.get("/api/workspaces/{workspace_id}/members", response_model=List[dict])
async def list_members(workspace_id: str, user: dict = Depends(get_current_user)):
    return await member_service.list_workspace_members(workspace_id, user["id"])


@router.post("/api/workspaces/{workspace_id}/invitations", response_model=dict)
async def invite_member(
    workspace_id: str,
    payload: InvitePayload,
    user: dict = Depends(get_current_user)
):
    return await member_service.invite_member(
        workspace_id=workspace_id,
        inviter_id=user["id"],
        target_email=payload.email,
        role=payload.role,
        inviter_name_override=payload.inviter_name
    )


@router.get("/api/workspaces/{workspace_id}/invitations", response_model=List[dict])
async def list_workspace_invitations(
    workspace_id: str,
    user: dict = Depends(get_current_user)
):
    return await member_service.list_workspace_pending_invitations(workspace_id, user["id"])


@router.delete("/api/workspaces/{workspace_id}/invitations/{invitation_id}")
async def cancel_invitation(
    workspace_id: str,
    invitation_id: str,
    user: dict = Depends(get_current_user)
):
    await member_service.cancel_workspace_invitation(workspace_id, user["id"], invitation_id)
    return {"status": "cancelled", "invitation_id": invitation_id}


@router.delete("/api/workspaces/{workspace_id}/members/{target_user_id}")
async def remove_member(
    workspace_id: str,
    target_user_id: str,
    user: dict = Depends(get_current_user)
):
    await member_service.remove_member(workspace_id, user["id"], target_user_id)
    return {"status": "removed"}


@router.get("/api/invitations", response_model=List[dict])
async def list_user_invitations(
    user: dict = Depends(get_current_user),
    x_user_email: str | None = Header(None, alias="X-User-Email")
):
    email = user.get("email") or x_user_email or ""
    return await member_service.list_pending_invitations_for_user(email)


@router.post("/api/invitations/{invitation_id}/accept", response_model=dict)
async def accept_invitation(invitation_id: str, user: dict = Depends(get_current_user)):
    return await member_service.accept_invitation(invitation_id, user)


@router.post("/api/invitations/{invitation_id}/reject", response_model=dict)
async def reject_invitation(invitation_id: str, user: dict = Depends(get_current_user)):
    return await member_service.reject_invitation(invitation_id, user)
