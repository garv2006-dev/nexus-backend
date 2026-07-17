"""
Verifies Clerk session tokens and resolves the current user's Mongo document,
creating it on first sight and lazily resetting their credit balance once the
reset window has passed.
"""

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient

from .config import get_settings
from .database import users_collection

settings = get_settings()


@lru_cache
def _jwk_client() -> PyJWKClient:
    if not settings.clerk_jwks_url:
        raise RuntimeError(
            "CLERK_JWKS_URL is not set. Add it to backend/.env (see .env.example)."
        )
    return PyJWKClient(settings.clerk_jwks_url)


async def get_current_claims(authorization: str | None = Header(None)) -> dict:
    """Extracts and verifies the Clerk session JWT from the Authorization header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()

    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid session token: {exc}")

    return claims


async def get_current_user(claims: dict = Depends(get_current_claims)) -> dict:
    """
    Returns the Mongo user document for the verified token, creating it with a
    fresh credit balance on first sight, and lazily resetting credits once the
    reset window (CREDIT_RESET_HOURS) has elapsed.
    """
    users = users_collection()
    user_id = claims["sub"]
    now = datetime.now(timezone.utc)

    user = await users.find_one({"_id": user_id})

    if user is None:
        user = {
            "_id": user_id,
            "email": claims.get("email", ""),
            "name": claims.get("name", "New user"),
            "avatar_url": None,
            "bio": None,
            "credits": settings.credit_limit,
            "credits_reset_at": now + timedelta(hours=settings.credit_reset_hours),
            "created_at": now,
        }
        await users.insert_one(user)
        return user

    reset_at = user["credits_reset_at"]
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)

    if now >= reset_at:
        new_reset = now + timedelta(hours=settings.credit_reset_hours)
        await users.update_one(
            {"_id": user_id},
            {"$set": {"credits": settings.credit_limit, "credits_reset_at": new_reset}},
        )
        user["credits"] = settings.credit_limit
        user["credits_reset_at"] = new_reset

    return user
