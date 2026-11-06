"""
The recipe index: one entry per stored recipe with its title, book, and
the ingredients it needs, built once (at the end of ingest, or by
tools/build_recipe_index.py) so matching "what can I make with these"
never has to re-parse a recipe at query time.

Built from what's already in Chroma, using the same parsing scale.py
does, so a parser change only needs the index rebuilt, not a re-ingest
(re-embedding is the slow part on the Pi).

Entry shape:
    recipe_id, book, title,
    match_title   the title without a "with ..." tail, and
    aliases       extra titles from the book's TITLE_ALIASES, both for
                  title lookup (query_utils/title_lookup.py)
    page, page_confirmed,
    ingredients   required ingredients, each {"name": the normalized
                  name, for display ("unsalted butter or shortening"),
                  "options": the names that satisfy it (["unsalted
                  butter", "shortening"], see ingredient_names.options)}
    optional      same shape, for garnishes, pan grease, "(optional)"
                  lines and everything in an optional group
    sub_recipes   other recipes it calls for, as written ("Brioche
                  Dough (this page)"), not matched for now
    your_choice   required placeholders that can't be matched ("prepared
                  fruit" in an any-fruit recipe), shown, never counted
    groups        group name -> batch / component / optional
"""

import json
import os
from collections import defaultdict

from books import profile_for_book, strategy_for
from common.config import RECIPE_INDEX_PATH
from match_utils.ingredient_names import normalize, options, pieces
from query_utils.recipe_matching import display_title, extract_title
from scale_utils.ingredients import extract_ingredient_groups


def load_recipes():
    """Every recipe in the database as {recipe_id: {"book", "text",
    "chunk_ids", "page", "page_confirmed"}}, with split recipes stitched
    back together by recipe_id (same as query_utils.retrieval.
    full_recipe_text, but for all of them at once). Page info comes from
    part 0, where the recipe starts."""
    from query_utils.retrieval import get_collection  # needs chromadb, so imported late

    result = get_collection().get(where={"content_type": "recipe"},
                                  include=["documents", "metadatas"])
    parts = defaultdict(list)
    first_meta = {}
    chunk_ids = defaultdict(list)
    for chunk_id, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
        # Chunks ingested before recipe_id existed are each their own recipe.
        key = meta.get("recipe_id") or chunk_id
        part = meta.get("part", 0)
        parts[key].append((part, doc))
        if part == 0 or key not in first_meta:
            first_meta[key] = meta
        chunk_ids[key].append(chunk_id)
    return {key: {"book": first_meta[key]["book"],
                  "text": "\n".join(doc for _, doc in sorted(chunks, key=lambda c: c[0])),
                  "chunk_ids": chunk_ids[key],
                  "page": first_meta[key].get("page", 0),
                  "page_confirmed": first_meta[key].get("page_confirmed", False)}
            for key, chunks in parts.items()}


def _add(target, name):
    if all(entry["name"] != name for entry in target):
        target.append({"name": name, "options": options(name)})


def index_entry(recipe_id, recipe):
    """One recipe's index entry, or None for a book with no recipe-aware
    profile (its chunks are never tagged as recipes anyway)."""
    book, text = recipe["book"], recipe["text"]
    strategy = strategy_for(book)
    if strategy is None:
        return None
    groups = extract_ingredient_groups(text, strategy)

    required, optional, sub_recipes, your_choice = [], [], [], []
    for group_name, ingredients in groups.items():
        in_optional_group = groups.kinds.get(group_name) == "optional"
        for ing in ingredients:
            name, flags = normalize(ing["name"])
            if not name:
                continue
            if "ignored" in flags:
                # A placeholder like "prepared fruit" can't be matched, but
                # it's still something the recipe needs.
                if not in_optional_group and "optional" not in flags and name not in your_choice:
                    your_choice.append(name)
                continue
            if "sub_recipe" in flags:
                if ing["name"] not in sub_recipes:
                    sub_recipes.append(ing["name"])
                continue
            target = optional if in_optional_group or "optional" in flags else required
            # The same ingredient in two batches, or in two components,
            # is still one thing the recipe needs.
            for piece in pieces(name, ing.get("unmeasured")):
                _add(target, piece)

    # An ingredient that's required somewhere isn't also optional.
    required_names = {entry["name"] for entry in required}
    optional = [entry for entry in optional if entry["name"] not in required_names]

    printed_title = extract_title(text, book) or ""
    return {
        "recipe_id": recipe_id,
        "book": book,
        "title": display_title(printed_title or recipe_id),
        "match_title": extract_title(text, book, include_subtitle=False) or "",
        "aliases": profile_for_book(book).title_aliases(printed_title),
        "page": recipe["page"],
        "page_confirmed": recipe["page_confirmed"],
        "ingredients": required,
        "optional": optional,
        "sub_recipes": sub_recipes,
        "your_choice": your_choice,
        "groups": {name: groups.kinds[name] for name in groups if name != "default"},
    }


def build_index():
    """The index for every recipe in the database, sorted by book, then
    title."""
    entries = [e for e in (index_entry(key, r) for key, r in load_recipes().items()) if e]
    return sorted(entries, key=lambda e: (e["book"], e["title"].lower()))


def save_index(entries, path=RECIPE_INDEX_PATH):
    # Written to a temporary file first, so a crash mid-write never
    # leaves a half-written index behind.
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"recipes": entries}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_index(path=RECIPE_INDEX_PATH):
    """The saved index entries, or None if it hasn't been built yet."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["recipes"]
    except FileNotFoundError:
        return None


def summarize(entries):
    """A few lines describing the index, printed after building it."""
    books = defaultdict(int)
    for e in entries:
        books[e["book"]] += 1
    lines = [f"Recipe index: {len(entries)} recipes"]
    lines += [f"  {book}: {n}" for book, n in sorted(books.items())]
    no_ingredients = [e["title"] for e in entries if not e["ingredients"]]
    if no_ingredients:
        lines.append(f"  {len(no_ingredients)} with no required ingredients: "
                     + ", ".join(no_ingredients[:8]) + (", ..." if len(no_ingredients) > 8 else ""))
    choices = sum(1 for e in entries for i in e["ingredients"] + e["optional"] if len(i["options"]) > 1)
    lines.append(f"  {choices} ingredient choices (\"X or Y\") split into options")
    return lines
