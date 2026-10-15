"""
Embedding calls for both sides of retrieval, kept side by side on
purpose. nomic-embed-text was trained with task prefixes: stored chunks
must be embedded with "search_document:" and questions with
"search_query:". A mismatch between ingest.py and query.py would quietly
break retrieval quality even though nothing would error out.
"""

import ollama

from common.config import EMBED_MODEL


def embed_document(text):
    """Embed text that is something to be *found* (a stored chunk)."""
    return ollama.embeddings(model=EMBED_MODEL, prompt=f"search_document: {text}")["embedding"]


def embed_query(text):
    """Embed text that is doing the *finding* (a user's question)."""
    return ollama.embeddings(model=EMBED_MODEL, prompt=f"search_query: {text}")["embedding"]
