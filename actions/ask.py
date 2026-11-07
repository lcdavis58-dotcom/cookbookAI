"""
Ask a question about your recipes: a recipe the question names is shown
as the book's exact text; several are listed to pick from; anything else
goes to the model with the closest book excerpts. See query.py.
"""

import time
from dataclasses import dataclass, field

import ollama

from common import cli
from query_utils.recipe_matching import extract_title, semantic_top_recipe_guess
from query_utils.retrieval import candidate_text, retrieve, within_distance
from query_utils.title_lookup import find_recipes

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


@dataclass
class AskResult:
    """What ask() found. kind is one of:
        "recipe"    the question names one recipe: recipe, text
        "choices"   it names several: choices (best first, at most
                    title_lookup.MAX_LISTED), more (how many past those)
        "answer"    the model answered from the closest excerpts: answer,
                    sources (the hits it was given), generation_time
        "nothing"   nothing in the books is close to the question
    warnings are problems worth showing whatever the kind (a recipe in the
    index but not the database)."""
    kind: str
    question: str
    recipe: object = None           # title_lookup.Candidate
    text: str = ""
    choices: list = field(default_factory=list)
    more: int = 0
    answer: str = ""
    sources: list = field(default_factory=list)
    generation_time: float = 0.0
    warnings: list = field(default_factory=list)


def build_context(hits):
    parts = []
    for h in hits:
        if h["page_confirmed"]:
            label = f"[{h['book']}, page {h['page']}]"
        else:
            label = f"[{h['book']}, page unknown]"
        parts.append(f"{label}\n{h['text']}")
    return "\n\n---\n\n".join(parts)


def page_note(candidate):
    entry = candidate.payload
    return f"p.{entry['page']}" if entry.get("page_confirmed") else "page unknown"


def run(question):
    # Title lookup searches every recipe in the recipe index; only the
    # LLM fallback below is limited to hits within MAX_DISTANCE.
    hits = retrieve(question)
    relevant = within_distance(hits)
    found, source = find_recipes(question, hits)
    # Only a title the question names in full is shown directly. A near
    # miss ("partial") goes to the model with the closest chunks, since a
    # question can mention a dish in passing ("what goes with banana
    # bread?") without asking for that recipe.
    header_matches = found.matches if found.kind == "match" else []

    # Diagnostic comparison, not used for the actual decision below.
    # Prints what a pure-embedding-distance approach would have guessed,
    # so real queries can be checked for agreement/disagreement over time
    # before considering whether to trust this signal for anything.
    if cli.DEBUG:
        semantic_guess = semantic_top_recipe_guess(relevant)
        semantic_title = (extract_title(semantic_guess["text"], semantic_guess["book"])
                          if semantic_guess else "(too close to call)")
        print(f"[debug] semantic-only guess: {semantic_title}  |  title lookup in the {source}: "
              f"{found.kind} {[c.title for c in found.matches] or ''}, typos read as {found.typos or '(none)'}, "
              f"books named: {found.books or '(none)'}")

    warnings = []
    if len(header_matches) == 1:
        c = header_matches[0]
        text = candidate_text(c)
        if text:
            return AskResult("recipe", question, recipe=c, text=text)
        warnings.append(f"[warning] '{c.title}' is in the recipe index but not the database; "
                        f"run tools/build_recipe_index.py to update the index.")

    if len(header_matches) > 1:
        return AskResult("choices", question, choices=header_matches, more=found.more)

    # No direct recipe title match, fall through to the LLM for passing
    # mentions, "similar to" style questions, or content_type="unknown"
    # books that have no recipe-aware chunking profile. Only the closest
    # LLM_CONTEXT_K hits get sent, keeping the prompt (and generation time)
    # small even though we searched more broadly above.
    if not relevant:
        return AskResult("nothing", question, warnings=warnings)
    llm_hits = relevant[:LLM_CONTEXT_K]
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
    return AskResult("answer", question, answer=response["message"]["content"], sources=llm_hits,
                     generation_time=time.time() - t0, warnings=warnings)


def render(result):
    """The result as the command line shows it."""
    lines = [f"{w}\n" for w in result.warnings]
    if result.kind == "recipe":
        c = result.recipe
        lines += [f"Found this directly in {c.book} ({page_note(c)}), showing the exact text:\n",
                  result.text,
                  "\n(matched instantly, no generation needed)"]
    elif result.kind == "choices":
        choices = result.choices
        total = len(choices) + result.more
        lines.append(f"I found {total} recipes matching \"{result.question}\". Which one did you mean?\n")
        lines += [f"  {i}. {c.title}  ({c.book}, {page_note(c)})" for i, c in enumerate(choices, 1)]
        if result.more:
            lines.append(f"  ...and {result.more} more.")
        first = choices[0]
        # The same name in two books: naming the book picks one.
        same_name = sum(c.title.lower() == first.title.lower() for c in choices) > 1
        example = f"{first.title.lower()} from {first.book}" if same_name else first.title.lower()
        lines += ["\nRun again with a more specific name (or the book's name) to see the full recipe, e.g.:",
                  f'  python3 query.py "recipe for {example}"',
                  "\n(matched instantly, no generation needed)"]
    elif result.kind == "nothing":
        lines.append("I couldn't find anything relevant to that in your cookbooks.")
    elif result.kind == "answer":
        lines += [result.answer,
                  f"\n(generation took {result.generation_time:.2f}s)",
                  "--- Retrieved from ---"]
        for h in result.sources:
            page_label = f"p.{h['page']}" if h["page_confirmed"] else "page unknown"
            lines.append(f"  {h['book']}, {page_label} (distance {h['distance']:.3f})")
    return "\n".join(lines)
