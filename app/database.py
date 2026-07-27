from motor.motor_asyncio import AsyncIOMotorClient

from .config import get_settings

settings = get_settings()

_client = None


def get_client():
    global _client
    if _client is None:
        if "localhost" in settings.mongodb_uri or "127.0.0.1" in settings.mongodb_uri:
            print("Using in-memory mongomock database!")
            from mongomock_motor import AsyncMongoMockClient
            _client = AsyncMongoMockClient()
        else:
            _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_database():
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
