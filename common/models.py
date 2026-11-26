"""
Every chat-model call goes through chat() here, so the model is named in
one place (CHAT_MODEL in common/config.py) and every call's time is
recorded. The chat saves CALLS with each reply, and
tools/diagnostics/model_timing.py summarizes them per model and job, for
deciding whether a bigger model is worth its time.
"""

import time

import ollama

from common.config import CHAT_CONTEXT, CHAT_MODEL, MODEL_TIMEOUT

# {"job", "model", "seconds"} per call since the last clear(); the chat
# clears it at the start of each turn.
CALLS = []

_client = None


def is_connection_error(error):
    """Ollama isn't running or can't be reached."""
    return isinstance(error, ConnectionError) or type(error).__name__ in ("ConnectError", "ConnectTimeout")


def is_timeout(error):
    """A model call ran past MODEL_TIMEOUT."""
    return isinstance(error, TimeoutError) or type(error).__name__ in ("ReadTimeout", "WriteTimeout", "PoolTimeout")


def chat(job, messages, tools=None, options=None, format=None, model=None):
    """ollama.chat with CHAT_MODEL. job names what the call is for
    ("route", "answer", "scale intent", "dish labels"). Every call gets
    the same context size (CHAT_CONTEXT), so the model is never reloaded
    between them. format="json" asks for a JSON reply. model overrides
    CHAT_MODEL for a job that runs once, not while she waits (the dish
    labels, LABEL_MODEL). Returns (response, seconds)."""
    global _client
    if _client is None:
        _client = ollama.Client(timeout=MODEL_TIMEOUT)
    options = {**(options or {}), "num_ctx": CHAT_CONTEXT}
    t0 = time.time()
    extra = {"format": format} if format else {}
    model = model or CHAT_MODEL
    response = _client.chat(model=model, messages=messages, tools=tools, options=options, **extra)
    seconds = time.time() - t0
    CALLS.append({"job": job, "model": model, "seconds": round(seconds, 2)})
    return response, seconds


def installed(name):
    """Whether Ollama has the model pulled: True, False, or None when
    Ollama can't be reached."""
    try:
        listing = ollama.Client(timeout=5).list()
    except Exception:  # noqa: BLE001 - not reachable, whatever the reason
        return None
    names = {getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None)
             for m in (getattr(listing, "models", None) or listing.get("models", []))}
    return name in names or f"{name}:latest" in names


def clear():
    CALLS.clear()
