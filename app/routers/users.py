from fastapi import APIRouter, Depends

from .. import schemas
from ..auth import get_current_user
from ..database import users_collection

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_user_out(doc: dict) -> schemas.UserOut:
    return schemas.UserOut(
        id=doc["_id"],
        email=doc.get("email", ""),
        name=doc.get("name", ""),
        avatar_url=doc.get("avatar_url"),
        bio=doc.get("bio"),
        credits=doc["credits"],
        credits_reset_at=doc["credits_reset_at"],
        created_at=doc["created_at"],
    )


@router.get("/me", response_model=schemas.UserOut)
async def get_me(user: dict = Depends(get_current_user)):
    return _to_user_out(user)


@router.post("/sync", response_model=schemas.UserOut)
async def sync_me(payload: schemas.UserSync, user: dict = Depends(get_current_user)):
    """
    Called once right after Clerk sign-in so we have display info (Clerk's
    session token doesn't carry email/name by default). Never touches credits.
    """
    updates = {"email": payload.email, "name": payload.name}
    if payload.avatar_url:
        updates["avatar_url"] = payload.avatar_url

    await users_collection().update_one({"_id": user["_id"]}, {"$set": updates})
    user.update(updates)
    return _to_user_out(user)


@router.patch("/me", response_model=schemas.UserOut)
async def update_me(payload: schemas.ProfileUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        await users_collection().update_one({"_id": user["_id"]}, {"$set": updates})
        user.update(updates)
    return _to_user_out(user)
