from fastapi import APIRouter, Depends
from ..auth import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=dict)
async def get_me(user: dict = Depends(get_current_user)):
    return user
