from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..database import fetch_one

router = APIRouter(prefix="/api/users", tags=["users"])


class UserProfileUpdatePayload(BaseModel):
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")

    class Config:
        populate_by_name = True


@router.get("/me", response_model=dict)
async def get_me(user: dict = Depends(get_current_user)):
    return user


async def _update_user_profile(user_id: str, payload: UserProfileUpdatePayload) -> dict:
    first_name = payload.first_name.strip() if payload.first_name is not None else None
    last_name = payload.last_name.strip() if payload.last_name is not None else None
    
    name = payload.name.strip() if payload.name is not None else None
    if first_name is not None or last_name is not None:
        fn = first_name if first_name is not None else ""
        ln = last_name if last_name is not None else ""
        computed = f"{fn} {ln}".strip()
        if computed:
            name = computed

    updates = []
    params = [user_id]

    if first_name is not None:
        params.append(first_name)
        updates.append(f"first_name = ${len(params)}")

    if last_name is not None:
        params.append(last_name)
        updates.append(f"last_name = ${len(params)}")

    if name is not None and name != "":
        params.append(name)
        updates.append(f"name = ${len(params)}")

    if payload.email is not None and payload.email.strip() != "":
        params.append(payload.email.strip().lower())
        updates.append(f"email = ${len(params)}")

    if payload.avatar_url is not None:
        params.append(payload.avatar_url)
        updates.append(f"avatar_url = ${len(params)}")

    if not updates:
        user = await fetch_one("SELECT * FROM users WHERE id = $1", user_id)
        return dict(user) if user else {}

    query = f"""
        UPDATE users
        SET {', '.join(updates)}
        WHERE id = $1
        RETURNING *
    """
    updated = await fetch_one(query, *params)
    return dict(updated) if updated else {}


@router.patch("/me", response_model=dict)
async def update_me(payload: UserProfileUpdatePayload, user: dict = Depends(get_current_user)):
    return await _update_user_profile(user["id"], payload)


@router.post("/sync", response_model=dict)
async def sync_me(payload: UserProfileUpdatePayload, user: dict = Depends(get_current_user)):
    return await _update_user_profile(user["id"], payload)
