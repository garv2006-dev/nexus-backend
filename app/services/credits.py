"""Credit (rate-limit) bookkeeping: 1 credit per user message sent."""

from fastapi import HTTPException

from ..database import users_collection


async def ensure_and_consume_credit(user: dict) -> None:
    """
    Raises 402 if the user has no credits left, otherwise deducts one credit.
    `user` is the dict returned by `get_current_user`, which has already been
    lazily reset if the reset window elapsed.
    """
    if user["credits"] <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "You're out of credits for now.",
                "credits_reset_at": user["credits_reset_at"].isoformat(),
            },
        )

    await users_collection().update_one({"_id": user["_id"]}, {"$inc": {"credits": -1}})
    user["credits"] -= 1
