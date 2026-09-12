from fastapi import APIRouter, Depends
from ..auth import get_current_user
from ..services import usage_service

router = APIRouter(prefix="/api/workspaces/{workspace_id}/usage", tags=["usage"])


@router.get("", response_model=dict)
async def get_workspace_usage(workspace_id: str, user: dict = Depends(get_current_user)):
    today_stats = await usage_service.get_workspace_today_usage(workspace_id, user["id"])
    history = await usage_service.get_usage_history(workspace_id, user["id"], days=14)
    return {
        **today_stats,
        "history": history
    }
