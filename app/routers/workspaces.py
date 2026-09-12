from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..services import workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class WorkspaceUpdatePayload(BaseModel):
    name: Optional[str] = None
    plan_type: Optional[str] = None
    max_members: Optional[int] = Field(None, ge=1, le=100)
    daily_token_limit: Optional[int] = Field(None, ge=1000, le=10000000)
    max_pages: Optional[int] = Field(None, ge=1, le=100000)


@router.get("", response_model=List[dict])
async def list_workspaces(user: dict = Depends(get_current_user)):
    return await workspace_service.list_user_workspaces(user["id"])


@router.post("", response_model=dict)
async def create_workspace(payload: WorkspaceCreatePayload, user: dict = Depends(get_current_user)):
    return await workspace_service.create_workspace(user["id"], payload.name)


@router.get("/{workspace_id}", response_model=dict)
async def get_workspace(workspace_id: str, user: dict = Depends(get_current_user)):
    return await workspace_service.get_workspace_details(workspace_id, user["id"])


@router.patch("/{workspace_id}/settings", response_model=dict)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdatePayload,
    user: dict = Depends(get_current_user)
):
    return await workspace_service.update_workspace_settings(
        workspace_id=workspace_id,
        user_id=user["id"],
        name=payload.name,
        plan_type=payload.plan_type,
        max_members=payload.max_members,
        daily_token_limit=payload.daily_token_limit,
        max_pages=payload.max_pages
    )


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: str, user: dict = Depends(get_current_user)):
    await workspace_service.delete_workspace(workspace_id, user["id"])
    return {"status": "deleted", "workspace_id": workspace_id}
