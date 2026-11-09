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


def chat(job, messages, tools=None, options=None):
    """ollama.chat with CHAT_MODEL. job names what the call is for
    ("route", "answer", "scale intent"). Every call gets the same context
    size (CHAT_CONTEXT), so the model is never reloaded between them.
    Returns (response, seconds)."""
    global _client
    if _client is None:
        _client = ollama.Client(timeout=MODEL_TIMEOUT)
    options = {**(options or {}), "num_ctx": CHAT_CONTEXT}
    t0 = time.time()
    response = _client.chat(model=CHAT_MODEL, messages=messages, tools=tools, options=options)
    seconds = time.time() - t0
    CALLS.append({"job": job, "model": CHAT_MODEL, "seconds": round(seconds, 2)})
    return response, seconds


def clear():
    CALLS.clear()
