from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import get_settings

settings = get_settings()

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongodb_db_name]


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


# Convenience collection accessors -------------------------------------------------

def users_collection():
    return get_database()["users"]


def sessions_collection():
    return get_database()["chat_sessions"]


def messages_collection():
    return get_database()["chat_messages"]
