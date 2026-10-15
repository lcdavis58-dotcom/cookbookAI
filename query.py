"""
Ask a question against your ingested cookbooks.

Run:
    python3 query.py "What page has a recipe for chicken tikka masala?"
    python3 query.py -d "recipe for sweet tart dough"    # with debug output

Where things live:
    query_utils/retrieval.py         vector search, split-recipe reassembly
    query_utils/recipe_matching.py   titles, yield lines, title-word matching

Requires the same packages as ingest.py, plus your chat model pulled, e.g.:
    ollama pull llama3.2:1b
"""

import time

import ollama

from common import cli
from query_utils.recipe_matching import (display_title, extract_title,
                                         find_recipe_header_matches, semantic_top_recipe_guess)
from query_utils.retrieval import full_recipe_text, retrieve

CHAT_MODEL = "llama3.2:1b"  # or your custom "cookbook-assistant" model

# How many of the retrieved chunks get pasted into the prompt if we fall
# through to generation. Kept small, a bigger prompt directly costs more
# time on the Pi's CPU (see TITLE_SEARCH_K in query_utils/retrieval.py for
# the wider search this is a slice of).
LLM_CONTEXT_K = 6

SYSTEM_PROMPT = """You are a cookbook assistant. You may ONLY use the recipe
excerpts provided below to answer. Do not use any outside knowledge, even if
you recognize the dish.

Rules:
- If the excerpts don't contain enough information to answer, say so plainly
  and stop there. Do not guess, do not suggest what a recipe "might be," and
  do not recommend any book, cookbook, or source that isn't one of the
  excerpts given to you. If it isn't in the excerpts, it doesn't exist as
  far as you're concerned.
- Never name a specific dish (like "this is probably a lasagna recipe")
  unless the excerpt itself explicitly names it. Guessing based on
  ingredients alone is not allowed.
- Treat each excerpt as a SEPARATE, independent source. Never combine
  ingredients, instructions, or steps from two different excerpts into one
  answer, even if they mention the same dish. If no single excerpt fully
  answers the question, say what you found in each excerpt separately
  instead of merging them.
- Quote quantities, yields, measurements, and ingredient amounts EXACTLY as
  written in the excerpt. Do not convert units, do not combine multiple
  batch sizes into a summary or range, and do not paraphrase numbers in any
  way. Copy them character for character. Do not add any closing note,
  estimate, or interpretation of a yield or quantity beyond restating it
  exactly as written.
- Always cite the book title for any recipe you reference. Include the page
  number ONLY if it's given as an actual number, if an excerpt is marked
  "page unknown," cite the book and recipe name only, do not invent a page
  number under any circumstances.
- If asked to scale a recipe, extract the ingredient list exactly as written
  and note the original serving size, but do not do the math yourself.
"""


def build_context(hits):
    parts = []
    for h in hits:
        if h["page_confirmed"]:
            label = f"[{h['book']}, page {h['page']}]"
        else:
            label = f"[{h['book']}, page unknown]"
        parts.append(f"{label}\n{h['text']}")
    return "\n\n---\n\n".join(parts)


def ask(question):
    hits = retrieve(question)

    if not hits:
        print("I couldn't find anything relevant to that in your cookbooks.")
        return

    header_matches = find_recipe_header_matches(hits, question)

    # Diagnostic comparison, not used for the actual decision below.
    # Prints what a pure-embedding-distance approach would have guessed,
    # so real queries can be checked for agreement/disagreement over time
    # before considering whether to trust this signal for anything.
    if cli.DEBUG:
        semantic_guess = semantic_top_recipe_guess(hits)
        semantic_title = (extract_title(semantic_guess["text"], semantic_guess["book"])
                          if semantic_guess else "(too close to call)")
        word_match_titles = [extract_title(h["text"], h["book"]) for h in header_matches]
        print(f"[debug] semantic-only guess: {semantic_title}  |  "
              f"title-word match(es): {word_match_titles or '(none)'}")

    if len(header_matches) == 1:
        h = header_matches[0]
        page_label = f"p.{h['page']}" if h["page_confirmed"] else "page unknown"
        print(f"Found this directly in {h['book']} ({page_label}), showing the exact text:\n")
        print(full_recipe_text(h))
        print(f"\n(matched instantly, no generation needed, distance {h['distance']:.1f})")
        return

    if len(header_matches) > 1:
        print(f"I found {len(header_matches)} recipes matching \"{question}\". Which one did you mean?\n")
        for i, h in enumerate(header_matches, 1):
            title = display_title(extract_title(h["text"], h["book"]))
            page_label = f"p.{h['page']}" if h["page_confirmed"] else "page unknown"
            print(f"  {i}. {title}  ({h['book']}, {page_label})")
        example_title = extract_title(header_matches[0]["text"], header_matches[0]["book"]).lower()
        print(f"\nRun again with a more specific name to see the full recipe, e.g.:")
        print(f'  python3 query.py "recipe for {example_title}"')
        print("\n(matched instantly, no generation needed)")
        return

    # No direct recipe title match, fall through to the LLM for passing
    # mentions, "similar to" style questions, or content_type="unknown"
    # books that have no recipe-aware chunking profile. Only the closest
    # LLM_CONTEXT_K hits get sent, keeping the prompt (and generation time)
    # small even though we searched more broadly above.
    llm_hits = hits[:LLM_CONTEXT_K]
    context = build_context(llm_hits)
    user_prompt = f"Cookbook excerpts:\n\n{context}\n\nQuestion: {question}"

    t0 = time.time()
    response = ollama.chat(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": 0.2, "num_ctx": 2048},
    )
    generation_time = time.time() - t0

    print(response["message"]["content"])
    print(f"\n(generation took {generation_time:.2f}s)")
    print("--- Retrieved from ---")
    for h in llm_hits:
        page_label = f"p.{h['page']}" if h["page_confirmed"] else "page unknown"
        print(f"  {h['book']}, {page_label} (distance {h['distance']:.3f})")


if __name__ == "__main__":
    question, cli.DEBUG = cli.parse_cli("Ask a question against your ingested cookbooks.")
    ask(question)
