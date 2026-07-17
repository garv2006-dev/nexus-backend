from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# --- Users / profile -----------------------------------------------------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str  # Clerk user id
    email: str
    name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    credits: int
    credits_reset_at: datetime
    created_at: datetime


class UserSync(BaseModel):
    """Sent once after Clerk sign-in so we have display info to store locally."""

    email: str
    name: str
    avatar_url: Optional[str] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


# --- Chat ------------------------------------------------------------------

class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    created_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime


class SessionDetailOut(SessionOut):
    messages: list[MessageOut] = []


class SessionCreate(BaseModel):
    title: Optional[str] = None


class SessionRename(BaseModel):
    title: str


class MessageCreate(BaseModel):
    content: str
