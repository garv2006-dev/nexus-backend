"""
Thin abstraction over multiple AI providers so the rest of the app can just
call `generate_reply_stream(provider, messages)` and get an async generator
of text chunks back, regardless of which provider is configured.
"""

import asyncio
import threading
from typing import AsyncGenerator, Iterable

from ..config import get_settings

settings = get_settings()

Message = dict  # {"role": "user" | "assistant", "content": str}


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

async def _stream_openai(messages: list[Message]) -> AsyncGenerator[str, None]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    stream = await client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _to_gemini_history(messages: list[Message]):
    """Gemini wants prior turns as history plus the latest message separately."""
    history = []
    for m in messages[:-1]:
        role = "user" if m["role"] == "user" else "model"
        history.append({"role": role, "parts": [m["content"]]})
    return history


async def _stream_gemini(messages: list[Message]) -> AsyncGenerator[str, None]:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)

    history = _to_gemini_history(messages)
    latest = messages[-1]["content"]

    def make_sync_stream() -> Iterable[str]:
        chat = model.start_chat(history=history)
        response = chat.send_message(latest, stream=True)
        for chunk in response:
            if chunk.text:
                yield chunk.text

    # The Gemini SDK is synchronous. Run it in a background thread and relay
    # chunks into an asyncio.Queue so callers can `async for` over it without
    # blocking the event loop.
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    sentinel = object()

    def worker():
        try:
            for item in make_sync_stream():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, Exception):
            raise item
        yield item


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def generate_reply_stream(
    provider: str, messages: list[Message]
) -> AsyncGenerator[str, None]:
    if provider == "gemini":
        async for chunk in _stream_gemini(messages):
            yield chunk
    else:
        async for chunk in _stream_openai(messages):
            yield chunk
