"""
Verifies Clerk session tokens, extracts authenticated user claims,
and syncs user records in Supabase PostgreSQL `users` table.
"""

from functools import lru_cache
import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient

from .config import get_settings
from .database import fetch_one, execute

settings = get_settings()


@lru_cache
def _jwk_client() -> PyJWKClient:
    if not settings.clerk_jwks_url:
        raise RuntimeError(
            "CLERK_JWKS_URL is not set. Add it to backend/.env."
        )
    return PyJWKClient(settings.clerk_jwks_url)


async def get_current_claims(authorization: str | None = Header(None)) -> dict:
    """Extracts and verifies the Clerk session JWT from the Authorization header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    token = authorization.split(" ", 1)[1].strip()

    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid session token: {exc}")

    return claims


def format_user_display_name(
    first_name: str | None = None,
    last_name: str | None = None,
    raw_name: str | None = None,
    email: str | None = None,
    user_id: str | None = None,
    default_fallback: str = "Workspace Member"
) -> str:
    """Consolidated helper to compute a clean user display name from available user attributes."""
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    full = f"{fn} {ln}".strip()
    if full:
        return full
    if raw_name and raw_name.strip() and not raw_name.strip().lower().startswith("user user_"):
        return raw_name.strip()
    if email and "@" in email:
        return email.split("@")[0].replace(".", " ").replace("_", " ").title()
    if user_id:
        return f"User {user_id[:8]}"
    return default_fallback


async def get_current_user(
    claims: dict = Depends(get_current_claims)
) -> dict:
    """
    Returns the user record from Supabase PostgreSQL, creating or updating
    it on first sight. Syncs user email strictly from authenticated claims.
    """
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID (sub) missing from token")

    email = (
        claims.get("email")
        or claims.get("email_address")
        or claims.get("primary_email_address")
    )
    if email:
        email = str(email).strip().lower()

    first_name = (claims.get("given_name") or claims.get("first_name") or "").strip() or None
    last_name = (claims.get("family_name") or claims.get("last_name") or "").strip() or None

    raw_name = claims.get("name") or claims.get("full_name")
    name = format_user_display_name(first_name, last_name, raw_name, email, user_id)

    avatar_url = claims.get("picture") or claims.get("image_url") or None


    user = await fetch_one("SELECT * FROM users WHERE id = $1", user_id)

    if user is None:
        query = """
            INSERT INTO users (id, email, name, first_name, last_name, avatar_url)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO UPDATE SET
                email = CASE WHEN EXCLUDED.email IS NOT NULL AND EXCLUDED.email != '' THEN EXCLUDED.email ELSE users.email END,
                name = CASE WHEN EXCLUDED.name IS NOT NULL AND EXCLUDED.name != '' THEN EXCLUDED.name ELSE users.name END,
                first_name = COALESCE(EXCLUDED.first_name, users.first_name),
                last_name = COALESCE(EXCLUDED.last_name, users.last_name),
                avatar_url = COALESCE(EXCLUDED.avatar_url, users.avatar_url)
            RETURNING *
        """
        user = await fetch_one(query, user_id, email, name, first_name, last_name, avatar_url)
    else:
        # Update user email, name, first_name, last_name, or avatar if updated
        updates = []
        params = [user_id]
        if email and user.get("email") != email:
            params.append(email)
            updates.append(f"email = ${len(params)}")
        if first_name and user.get("first_name") != first_name:
            params.append(first_name)
            updates.append(f"first_name = ${len(params)}")
        if last_name and user.get("last_name") != last_name:
            params.append(last_name)
            updates.append(f"last_name = ${len(params)}")
        if name and name != user.get("name") and not name.lower().startswith("user user_"):
            params.append(name)
            updates.append(f"name = ${len(params)}")
        if avatar_url and user.get("avatar_url") != avatar_url:
            params.append(avatar_url)
            updates.append(f"avatar_url = ${len(params)}")

        if updates:
            query = f"""
                UPDATE users
                SET {', '.join(updates)}
                WHERE id = $1
                RETURNING *
            """
            updated_user = await fetch_one(query, *params)
            if updated_user:
                user = dict(updated_user)

    return user
