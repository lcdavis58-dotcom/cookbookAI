"""
Working out which recipe a question is about, from retrieved chunks:
titles (via each book's own format rules), yield lines, and title-word
matching. Used by query.py and scale.py.
"""

import re
import string

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
    if not title.isupper():
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


def strip_book_name_mentions(question, book_names):
    """Remove any mention of a known book's name from the question before
    it's tokenized for title matching. Without this, a book whose own
    name shares a word with one of its recipe titles (this book is named
    "The Book On Pie" and contains a recipe literally titled "Pie") would
    false-match any question that names the book, since the word "pie"
    shows up either way, for entirely unrelated reasons. Matches
    case-insensitively and ignores surrounding quotes, since people
    naturally quote book names ("...from 'The Book on Pie'").
    """
    cleaned = question
    for book in book_names:
        if book:
            cleaned = re.sub(re.escape(book), " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def find_recipe_header_matches(hits, question):
    """Check ALL retrieved chunks for recipes whose title matches the
    question, not just the first one found. A vague query like "whipped
    cream" can genuinely match several distinct recipes in the same book,
    and picking just one to show would silently hide the others. Returns
    a list of matching hits (deduplicated by title), in the order they
    were retrieved (closest match first).

    Matching direction matters here: this requires every word IN THE
    TITLE to appear somewhere in the question, not the other way around.
    A lookup question is short and close to the title ("recipe for
    classic whipped cream"), but a real request can carry a lot of
    unrelated phrasing around the recipe name ("please double the classic
    whipped cream recipe from 'The Book On Pie'"), requiring every
    question word to also appear in the title would fail on that kind of
    phrasing, since words like "double" or "book" will never be in a
    title. Titles are short and specific, so requiring full title
    coverage (regardless of what else is in the question) is the more
    robust check.

    When one matching title is entirely contained in another ("Pie" and
    "Pumpkin Pie", or "Whipped Cream" and "Classic Whipped Cream"), only
    the more specific one is kept: the question named the longer title,
    the shorter one just happens to share its words. Two titles with the
    same words in different books are both kept, that's a real choice.
    """
    book_names = {h.get("book") for h in hits}
    cleaned_question = strip_book_name_mentions(question, book_names)

    question_words = {w.strip(string.punctuation).lower() for w in cleaned_question.split()}
    question_words.discard("")
    if not question_words:
        return []

    matches = []
    seen_titles = set()
    for h in hits:
        # Only a recipe's first part starts with its title; a later part's
        # first line is just wherever the split fell.
        if h["content_type"] != "recipe" or h.get("part", 0) != 0:
            continue
        title = extract_title(h["text"], h["book"])
        if not title or title in seen_titles:
            continue
        match_title = extract_title(h["text"], h["book"], include_subtitle=False)
        title_words = [w.strip(string.punctuation).lower() for w in match_title.split()]
        title_words = [w for w in title_words if w]
        if title_words and all(tw in question_words for tw in title_words):
            matches.append((h, set(title_words)))
            seen_titles.add(title)
    return [h for h, words in matches
            if not any(words < other for _, other in matches)]


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
