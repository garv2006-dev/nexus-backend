from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


# --- Users / Profile -----------------------------------------------------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    created_at: Optional[datetime] = None


class UserProfileUpdatePayload(BaseModel):
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")

    class Config:
        populate_by_name = True


# --- Conversations & Messages -------------------------------------------

class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    sources: Optional[list] = None
    token_usage: Optional[int] = 0
    created_at: Optional[datetime] = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    user_id: str
    title: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConversationDetailOut(ConversationOut):
    messages: List[MessageOut] = []

