"""
Narrowing a long list (1.2.0): past NARROW_OVER recipes ("show me a
cookie recipe" finds 184), the chat asks her to narrow it down instead of
paging through them, and suggests how from the recipes themselves: the
title words they share most ("chocolate chip (15)") and the books that
have the most. Counted in code, so the numbers are exact.

She doesn't have to pick a suggestion. Her answer is read inside the
same recipes (the focus keeps them as a "narrow" list, chat/state.py):
    title words      "a chocolate chip one", "something with ginger"
    an ingredient    "with peanut butter", "without nuts", "no eggs"
    a book           "from dessert person"
    everything       "show them all", "all of them"
Still over NARROW_OVER, it asks again, keeping both answers ("cookie",
then "chocolate", then "no nuts"). Nothing left: it says so and keeps
waiting. A message that's plainly something else ("double the pie
crust") goes on to the usual rules instead.
"""

import re
from collections import Counter

from query_utils.title_lookup import (ASKING_WORDS, FILLER_WORDS, SOFT_WORDS, find_books, list_titles,
                                      title_tokens, word_forms)

# Past this many recipes, ask her to narrow it down.
NARROW_OVER = 30
# Title words offered, and books.
MOST_WORDS = 5
MOST_BOOKS = 3
# A suggestion has to cover at least this many recipes, and leave some out.
MIN_SHARED = 2
# How often two words have to come together to be offered as one phrase.
TOGETHER = 0.7

SHOW_ALL_RE = re.compile(r"^\s*(?:(?:ok(?:ay)?|just|fine|no)[,\s]+)*(?:show|list|give)?\s*(?:me\s+)?"
                         r"(?:them\s+)?(?:all|every\s*(?:one|thing)|the\s+whole\s+list|everything)"
                         r"(?:\s+of\s+them)?(?:\s+(?:of\s+)?them)?(?:\s+please)?\s*[.!]*\s*$", re.I)
# Words in an answer that only point ("a chocolate chip one").
POINTING_WORDS = frozenset("""a an the one ones kind kinds type sort something some that those with any
    like maybe how about what i want id i'd please recipe recipes from in by book""".split())


def _skip(word, dish_forms):
    return (word in FILLER_WORDS or word in SOFT_WORDS or word.isdigit() or len(word) < 3
            or word_forms(word) & dish_forms or word_forms(word) & ASKING_WORDS)


def suggest(recipes, what):
    """[(phrase, count)] the titles share most, two-word phrases first
    when they're as common ("chocolate chip"), leaving out the dish's own
    words (what), then [(book, count)] for the books with the most."""
    dish_forms = set()
    for w in title_tokens(what):
        dish_forms |= word_forms(w)
    singles, pairs = Counter(), Counter()
    for c in recipes:
        # The title's core: no aside in parentheses, no "with ..." tail.
        words = list(c.variants[0][0]) if c.variants else title_tokens(c.title)
        kept = [w for w in words if not _skip(w, dish_forms)]
        singles.update(set(kept))
        pairs.update({f"{a} {b}" for a, b in zip(words, words[1:])
                      if not _skip(a, dish_forms) and not _skip(b, dish_forms)})
    total = len(recipes)
    chosen, covered = [], set()
    # A phrase when its words nearly always come together: "chip" is
    # almost always "chocolate chip". A word that's mostly in the phrase
    # isn't offered again on its own; "chocolate" still can be.
    for phrase, n in pairs.most_common():
        a, b = phrase.split()
        if MIN_SHARED <= n < total and n >= TOGETHER * min(singles[a], singles[b]):
            chosen.append((phrase, n))
            covered |= {w for w in (a, b) if singles[w] <= n / TOGETHER}
    chosen += [(w, n) for w, n in singles.items() if w not in covered and MIN_SHARED <= n < total]
    # Most common first; a tie goes to the phrase, then alphabetical.
    chosen.sort(key=lambda pn: (-pn[1], -len(pn[0].split()), pn[0]))
    books = Counter(c.book for c in recipes).most_common(MOST_BOOKS)
    return chosen[:MOST_WORDS], (books if len({c.book for c in recipes}) > 1 else [])


def question(count, what, words, books):
    """The reply asking her to narrow it down."""
    lines = [f"You have {count} {what}. Want to narrow it down?"]
    if words:
        lines.append(", ".join(f"{w} ({n})" for w, n in words) + ",")
    if books:
        lines.append("or from a book: " + ", ".join(f"{b} ({n})" for b, n in books) + ".")
    lines.append('Or say what you\'re after ("with peanut butter", "no nuts"), or "show them all".')
    return "\n".join(lines)


def options(words, books):
    """What the website offers to tap: each sends the message she could
    have typed."""
    return [w for w, _ in words] + [f"from {b}" for b, _ in books] + ["show them all"]


def title_words(message):
    """The words of an answer that could be in a title: "a chocolate
    chip one" -> "chocolate chip"."""
    return " ".join(w for w in title_tokens(message) if w not in POINTING_WORDS)


def by_title_or_book(message, recipes):
    """The recipes an answer names by title words or book; None when it
    names neither (so it may be an ingredient, or something else)."""
    books, rest = find_books(message, {c.book for c in recipes})
    words = title_words(rest)
    if words:
        found = list_titles(words, message, recipes)
        return found
    if books:
        return [c for c in recipes if c.book in books]
    return None
