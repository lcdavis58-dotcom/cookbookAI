"""
Vector search against the Chroma collection, and reassembly of recipes
that were stored in several parts. Used by query.py and scale.py.
"""

import time

import chromadb

from common import cli
from common.config import CHROMA_PATH, COLLECTION_NAME
from common.embeddings import embed_query

# Two different K values for two different jobs. Title lookup
# (query_utils/title_lookup.py) searches every title in the recipe index
# and only uses these hits to order equally good titles, or as the titles
# to search when the index hasn't been built; that fallback is why
# TITLE_SEARCH_K stays generous (plain vector search, no generation, so a
# wide net costs almost nothing). actions/ask.py's LLM_CONTEXT_K stays small, that's
# how many chunks actually get pasted into a prompt if we fall through to
# generation, and a bigger prompt directly costs more time on the Pi's CPU.
TITLE_SEARCH_K = 20

# Based on real data from this book: relevant whipped cream chunks topped
# out around 227, the best "irrelevant" match (a lasagna query against a
# pie book) came in at 264. This is a THIN margin from two data points,
# and it moves whenever chunks change: after recipes were re-chunked to
# keep their components, Classic Whipped Cream came in at 247 for "double
# the classic whipped cream". So it only decides what's close enough to
# hand to the model (within_distance), never whether a recipe named in
# the question is found: title lookup (query_utils/title_lookup.py) never
# looks at distance.
MAX_DISTANCE = 240


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(COLLECTION_NAME)


def retrieve(question, top_k=TITLE_SEARCH_K):
    """The top_k chunks closest to the question, closest first, however
    far away. Filter with within_distance for anything that should only
    see relevant chunks."""
    t0 = time.time()
    collection = get_collection()

    results = collection.query(
        query_embeddings=[embed_query(question)],
        n_results=top_k,
    )
    retrieval_time = time.time() - t0

    all_hits = []
    for doc, meta, distance in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        all_hits.append({
            "text": doc,
            "book": meta["book"],
            "page": meta["page"],
            "page_confirmed": meta["page_confirmed"],
            "content_type": meta.get("content_type", "unknown"),
            "distance": distance,
            # Absent on chunks ingested before recipes were split into
            # parts, those just behave as a one-part recipe.
            "recipe_id": meta.get("recipe_id"),
            "part": meta.get("part", 0),
            "part_count": meta.get("part_count", 1),
        })
    if cli.DEBUG:
        print(f"--- Retrieval debug (all candidates before filtering, {retrieval_time:.2f}s) ---")
        for h in all_hits:
            # Flatten newlines so each candidate stays on one line.
            preview = " / ".join(l.strip() for l in h["text"][:80].splitlines() if l.strip())
            kept = "" if h["distance"] <= MAX_DISTANCE else "  [over MAX_DISTANCE, title matching only]"
            part = f" part {h['part'] + 1}/{h['part_count']}" if h["part_count"] > 1 else ""
            print(f"  distance={h['distance']:.4f}  {h['book']} p.{h['page']} "
                  f"[{h['content_type']}{part}]  \"{preview}...\"{kept}")
        print("-----------------------------------------------------------")

    return all_hits


def within_distance(hits):
    """The hits close enough to the question to count as relevant: what
    gets handed to the model, and what decides "nothing relevant found"
    when no recipe title matched."""
    return [h for h in hits if h["distance"] <= MAX_DISTANCE]


def full_recipe_text(hit):
    """Return the complete text of the recipe a hit belongs to. A long
    recipe is stored as several line-boundary parts sharing a recipe_id
    (see chunk_recipe_aware in ingest_utils/chunking.py), and retrieval
    usually only returns one of them, so fetch every part and stitch them
    back together in order. Parts don't overlap, so joining them with a
    newline reproduces the original recipe exactly.

    Falls back to the hit's own text for a one-part recipe, or for chunks
    ingested before recipe_id existed.
    """
    if hit.get("part_count", 1) <= 1 or not hit.get("recipe_id"):
        return hit["text"]

    result = get_collection().get(where={"recipe_id": hit["recipe_id"]})
    parts = sorted(zip(result["metadatas"], result["documents"]), key=lambda p: p[0]["part"])
    if len(parts) != hit["part_count"]:
        print(f"[warning] expected {hit['part_count']} parts for {hit['recipe_id']}, "
              f"found {len(parts)}, the recipe below may be incomplete. Re-ingest this book.")
    return "\n".join(doc for _, doc in parts)


def recipe_text_by_id(recipe_id):
    """The complete text of a stored recipe, by its recipe_id (or, for a
    chunk ingested before recipe_id existed, its chunk id, which is what
    the recipe index uses then). "" when it isn't in the database, which
    means the recipe index is out of date."""
    collection = get_collection()
    result = collection.get(where={"recipe_id": recipe_id})
    if not result["ids"]:
        result = collection.get(ids=[recipe_id])
    parts = sorted(zip(result["metadatas"], result["documents"]), key=lambda p: p[0].get("part", 0))
    return "\n".join(doc for _, doc in parts)


def candidate_text(candidate):
    """The complete text of a recipe found by query_utils/title_lookup:
    from its retrieved chunk, or by its recipe_id for one found in the
    recipe index."""
    if "text" in candidate.payload:
        return full_recipe_text(candidate.payload)
    return recipe_text_by_id(candidate.key)
