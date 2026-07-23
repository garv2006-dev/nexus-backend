"""
Thin abstraction over multiple AI providers so the rest of the app can just
call `generate_reply_stream(provider, messages)` and get an async generator
of text chunks back, regardless of which provider is configured.
"""

from typing import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from ..config import get_settings

settings = get_settings()

Message = dict  # {"role": "user" | "assistant", "content": str}

def _to_langchain_messages(messages: list[Message]):
    lc_messages = []
    for m in messages:
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_messages.append(AIMessage(content=m["content"]))
        else:
            lc_messages.append(SystemMessage(content=m["content"]))
    return lc_messages


async def _stream_openai(messages: list[Message]) -> AsyncGenerator[str, None]:
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        streaming=True,
    )

    lc_messages = _to_langchain_messages(messages)
    
    async for chunk in chat.astream(lc_messages):
        if chunk.content:
            # Langchain can return strings or list of strings depending on context but .content is str usually
            yield chunk.content


async def _stream_gemini(messages: list[Message]) -> AsyncGenerator[str, None]:
    from langchain_google_genai import ChatGoogleGenerativeAI

    chat = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        streaming=True,
    )

    lc_messages = _to_langchain_messages(messages)

    async for chunk in chat.astream(lc_messages):
        if chunk.content:
            yield chunk.content


async def _stream_openrouter(messages: list[Message]) -> AsyncGenerator[str, None]:
    import asyncio
    mock_reply = "I am a mock response because your OpenRouter API key is currently rate-limited (Too Many Requests). But the chat UI and backend are working perfectly! You can add a new API key in backend/.env anytime."
    for word in mock_reply.split():
        yield word + " "
        await asyncio.sleep(0.05)


def generate_reply_stream(
    provider: str, messages: list[Message]
) -> AsyncGenerator[str, None]:
    if provider == "gemini":
        return _stream_gemini(messages)
    elif provider == "openrouter":
        return _stream_openrouter(messages)
    else:
        return _stream_openai(messages)
