"""
Reading recipe chunks: titles (via each book's own format rules) and
yield lines. Used by query.py, scale.py and the recipe index; which
recipe a question names is worked out in query_utils/title_lookup.py.
"""

import re

from books import profile_for_book


def extract_title(text, book=None, include_subtitle=True):
    """Pull out just the title line(s) at the very start of a recipe
    chunk, using whichever title format the chunk's book uses (see
    books/). Only ever looks at the first few lines, so intro
    prose further down in the chunk (which might coincidentally mention a
    different dish) never gets included in what we match against.

    include_subtitle only matters for books whose titles can carry a
    separate subtitle line (Dessert Person's "with X"). Title matching
    turns it off, since requiring every subtitle word in the question
    would make "scale the rice pudding cake" miss "Rice Pudding Cake
    with Mango Caramel".
    """
    return profile_for_book(book).extract_title(text, include_subtitle)


def display_title(title):
    """ALL-CAPS titles (Book on Pie) read better title-cased; titles that
    are already mixed case (Dessert Person) are left exactly as printed,
    so "with Mango Caramel" doesn't become "With Mango Caramel".
    str.title() starts a new word after an apostrophe ("Angel’S"), so
    the letter after one (or after "!", "Sh!t") is put back in lowercase,
    and so is a single letter ending a hyphenated word ("Peanut-y").
    Short joining words stay lowercase after the first word ("Cookies
    with Ganache", "Dulce de Leche"), and a short word of consonants
    other than y and h ("My", "Sh!t") is an abbreviation kept in
    capitals ("GF", "BBQ")."""
    # All-lowercase titles (Momofuku Milk Bar's "corn cookies") are
    # title-cased the same way.
    if not (title.isupper() or title.islower()):
        return title
    titled = re.sub(r"(?<=[’'!])[A-Z]", lambda m: m.group(0).lower(), title.title())
    titled = re.sub(r"(?<=\w-)[A-Z](?![\w’'])", lambda m: m.group(0).lower(), titled)
    titled = re.sub(r"\b[B-DFGJ-NP-TV-XZ][b-dfgj-np-tv-xz]{1,2}\b(?!\.)", lambda m: m.group(0).upper(), titled)
    small = r"(?:And|Or|With|Of|The|A|An|In|On|For|To|De)"
    return re.sub(rf"(?<=\s){small}(?=\s)|(?<=-){small}(?=-)", lambda m: m.group(0).lower(), titled)


def extract_yield_line(text):
    """Pull out the recipe's stated yield text, used as context for
    basis="yield" scaling requests. Grabs the MAKES (or SERVES, or
    BraveTart's YIELD:) line plus
    up to two following lines and joins them, since this text sometimes
    wraps across lines (the same DIFFICULTY-line-wrap quirk ingest works
    around during chunking). Returns "" if neither is found, the model is
    then told the yield is unknown rather than given a guess.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().upper().startswith(("MAKES", "SERVES", "YIELD:")):
            block = lines[i:i + 3]
            return " ".join(l.strip() for l in block if l.strip())
    return ""


def semantic_top_recipe_guess(hits, margin_ratio=1.15):
    """DIAGNOSTIC ONLY, not used to make any actual decision yet. Guesses
    the intended recipe purely from embedding distance, no title-word
    matching at all, returning the top recipe-tagged hit if it's clearly
    closer than the next one, or None if it's too close to call.

    This exists so real queries on the Pi can be compared side by side:
    does the discrete title-matching approach above agree with what pure
    semantic distance would have picked? Trusting distance alone shifts
    the correctness burden from our own testable, deterministic code onto
    the embedding model's judgment, that's worth validating against known-
    correct cases (like this one) before ever relying on it for anything.
    """
    recipe_hits = [h for h in hits if h["content_type"] == "recipe"]
    if not recipe_hits:
        return None
    if len(recipe_hits) == 1:
        return recipe_hits[0]
    best, second = recipe_hits[0], recipe_hits[1]
    if best["distance"] <= 0:
        return best
    if second["distance"] / best["distance"] >= margin_ratio:
        return best
    return None
