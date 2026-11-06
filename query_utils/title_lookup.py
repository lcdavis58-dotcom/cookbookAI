"""
Forgiving recipe title lookup: which recipe(s) a question names, checked
against every title in the recipe index (or, without an index, the
titles of the retrieved chunks). Used by scale.py and query.py.

Both the question and the titles are cut into the same kind of words
first (title_tokens), so these all count as the same word:
    case and accents     "CRÈME" / "creme"
    plurals              "cookies" / "cookie", "berries" / "berry",
                         "peaches" / "peach", "loaves" / "loaf"
    apostrophes          "angel's" / "angels", "s'mores" / "smores"
    hyphens              "deep-dish" / "deep dish"
    marks                "Milky Way®" / "milky way"
Filler words ("and", "with", "the", ...) are dropped on both sides, and
a misspelled question word ("choclate") matches the title word it's one
or two letters away from, but only when no title uses that word as
typed, so a real word ("pasta") never turns into another ("paste").

Every title then gets a score: how many of its words the question
names. A title's words are split in two:
    core    the title without its "with ..." tail ("Pasta" for "Pasta
            with Mushrooms"), all of which must be named for a match
    extra   the "with ..." words, which only add to the score, so
            "rice pudding cake" still finds "Rice Pudding Cake with
            Mango Caramel" and "pasta with mushrooms" picks "Pasta with
            Mushrooms" over the other "Pasta with ..." titles
A book module can give a recipe extra searchable titles (TITLE_ALIASES,
see books/engine.py), each scored like a title of its own.

A book named in the question ("from dessert persn", "from sfah") limits
the search to that book's recipes; see find_books for how forgiving
that is.

lookup() returns one of:
    "match"     titles whose core words are all in the question, at the
                best score: the question names them
    "partial"   no full title at the best score, but some titles share
                most of their words with it: the closest few, for the
                caller to offer ("Did you mean ...")
    "none"      nothing close
"""

import re
import string
import unicodedata
from dataclasses import dataclass, field

from books import profile_for_book
from query_utils.recipe_matching import display_title, extract_title

# Dropped from both the question and the titles: they join a title's
# words without telling recipes apart ("Sausage and Caramelized Onion
# Pie"), and a question may or may not use them.
FILLER_WORDS = {"a", "an", "and", "the", "with", "of", "or", "in", "on", "for", "to", "my", "your"}

# Words that praise a recipe more than name it. A title's own are scored
# like its "with ..." words (they count, but aren't needed), so "milky
# way bars" finds "Homemade Milky Way Bars".
SOFT_WORDS = {"homemade", "classic", "favorite", "favourite", "basic", "easy", "simple", "perfect",
              "best", "ultimate", "foolproof", "effortless", "famous", "everyday", "genius"}

# Words a scaling or lookup request is made of. They still count toward
# a full match ("double the double chocolate cake" names "Double
# Chocolate Cake"), but never toward a guess: "double the lasagna" isn't
# a near miss for "Double Crust".
REQUEST_WORDS = {"double", "doubled", "triple", "tripled", "quadruple", "half", "halve", "halved",
                 "quarter", "scale", "scaled", "recipe", "batch", "make", "making", "need", "want",
                 "please", "people", "serving", "servings", "serve", "serves", "feed", "feeds",
                 "only", "have", "can", "how", "what", "much", "many", "show", "find"}

# A shortened or misspelled book name only counts right after one of
# these ("lemon curd from dessert persn"); see find_books.
BOOK_CUE_WORDS = {"from", "in", "by", "using", "of"}

# Shortest acronym that names a book ("sfah"); see book_acronyms.
ACRONYM_MIN_LETTERS = 3

# A guess (a "partial" result) names at least this many of a title's
# words, or one word that's at least half the title ("brownies" for
# "Fudgy Brownies").
PARTIAL_MIN_WORDS = 2

# How many titles a "Did you mean" or "which one" list shows.
MAX_LISTED = 10

_DROP_CHARS_RE = re.compile(r"[’'`´®™©™®]")
_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def title_tokens(text):
    """The words of a title or question, lowercased, accents and marks
    removed, apostrophes closed up ("angel's" -> "angels"), split at
    hyphens and other punctuation, filler words and single letters
    (not digits) dropped. Plurals are left alone here; word_forms handles them."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _DROP_CHARS_RE.sub("", text.lower()).replace("&", " and ")
    # Single digits stay: they tell "Field Blend #1" from "Field Blend #2".
    return [w for w in _SPLIT_RE.split(text)
            if (len(w) > 1 or w.isdigit()) and w not in FILLER_WORDS]


def word_forms(word):
    """The forms a word may take as a plural or a singular, so two words
    match when their forms overlap ("cookies" and "cookie" share
    "cooky"; "peaches" and "peach" share "peach"). Some forms aren't
    real words ("quich" from "quiches"); that's harmless, since a match
    needs a form both words share, and "quiche" is one of them."""
    forms = {word}
    if len(word) <= 3:
        return frozenset(forms)
    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")              # berries -> berry, cookies -> cooky
    if word.endswith("ie") and len(word) > 4:
        forms.add(word[:-2] + "y")              # cookie -> cooky, brownie -> browny
    if word.endswith("ves"):
        forms.update({word[:-3] + "f", word[:-3] + "fe"})   # loaves -> loaf, knives -> knife
    if word.endswith("es"):
        forms.add(word[:-2])                    # peaches -> peach, tomatoes -> tomato
    if word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])                    # cookies -> cookie, quiches -> quiche
    return frozenset(forms)


def _edit_distance(a, b, limit):
    """Optimal string alignment distance (a swap of two neighbours counts
    as one edit), or limit + 1 once it's sure to be over limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1
                    and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def typo_limit(word):
    """How many letters a word of this length may have wrong: none under
    five letters (too many short words are one letter apart: "bar",
    "bark"), one up to seven, two after that."""
    if len(word) < 5:
        return 0
    return 1 if len(word) <= 7 else 2


@dataclass
class Candidate:
    """One recipe that a question might name."""
    key: str                # recipe_id, or the title for a hit without one
    book: str
    title: str              # as shown to the user
    variants: list          # (core words, extra words) per searchable title
    payload: dict = field(default=None, repr=False)   # the index entry or hit


def _split_soft(core, extra):
    """Move a title's SOFT_WORDS from its core to its extra words, unless
    that would leave no core at all."""
    soft = [w for w in core if w in SOFT_WORDS]
    if not soft or len(soft) == len(core):
        return core, extra
    return [w for w in core if w not in SOFT_WORDS], soft + extra


def _variants(match_title, full_title, aliases):
    core = list(dict.fromkeys(title_tokens(match_title)))
    extra = [w for w in dict.fromkeys(title_tokens(full_title)) if w not in core]
    variants = [_split_soft(core, extra)] if core else []
    for alias in aliases:
        words = list(dict.fromkeys(title_tokens(alias)))
        if words:
            variants.append(_split_soft(words, []))
    return variants


def candidates_from_index(entries):
    """A Candidate per recipe index entry. Entries from an index built
    before match_title was stored fall back to the display title."""
    out = []
    for e in entries:
        variants = _variants(e.get("match_title") or e["title"], e["title"], e.get("aliases", []))
        if variants:
            out.append(Candidate(e["recipe_id"], e["book"], e["title"], variants, e))
    return out


def candidates_from_hits(hits):
    """A Candidate per retrieved recipe chunk that starts a recipe (only
    a recipe's first part starts with its title), for when there's no
    recipe index to search."""
    out, seen = [], set()
    for h in hits:
        if h["content_type"] != "recipe" or h.get("part", 0) != 0:
            continue
        full = extract_title(h["text"], h["book"])
        if not full or (h["book"], full) in seen:
            continue
        seen.add((h["book"], full))
        match_title = extract_title(h["text"], h["book"], include_subtitle=False)
        aliases = profile_for_book(h["book"]).title_aliases(full)
        variants = _variants(match_title, full, aliases)
        if variants:
            out.append(Candidate(h.get("recipe_id") or full, h["book"], display_title(full), variants, h))
    return out


@dataclass
class Scored:
    candidate: Candidate
    score: int              # title words the question names
    guess: int              # ... by words that aren't REQUEST_WORDS
    total: int              # title words, core and extra
    full: bool              # every core word named
    exact: bool             # every word named, extra too
    extra_named: int        # extra words named


@dataclass
class LookupResult:
    kind: str               # "match", "partial" or "none"
    matches: list           # Candidates, best first, at most MAX_LISTED
    more: int = 0           # how many more there were past MAX_LISTED
    typos: dict = None      # question word -> the title words it was read as
    books: list = None      # the books the question names (see find_books)


def _words(text):
    """Every word of a text, normalized like title_tokens but with the
    filler words and single letters kept (book names are matched word
    for word, and acronyms are made from every word)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _DROP_CHARS_RE.sub("", text.lower()).replace("&", " and ")
    return [w for w in _SPLIT_RE.split(text) if w]


def _same_word(typed, word):
    """A question word stands for a book-name word: the same word, a
    plural of it, or a typo of it (see typo_limit)."""
    if word_forms(typed) & word_forms(word):
        return True
    limit = typo_limit(word)
    return bool(limit) and typed[0] == word[0] and _edit_distance(typed, word, limit) <= limit


def book_acronyms(book):
    """The acronyms a book goes by: the first letter of every word, with
    and without a leading "The" ("Salt Fat Acid Heat" -> "sfah", "The
    Book On Pie" -> "tbop" and "bop"). Only ACRONYM_MIN_LETTERS or
    longer: two letters ("dp") are too easily a unit or a stray word."""
    words = _words(book)
    acronyms = {"".join(w[0] for w in words)}
    if len(words) > 1 and words[0] == "the":
        acronyms.add("".join(w[0] for w in words[1:]))
    return {a for a in acronyms if len(a) >= ACRONYM_MIN_LETTERS}


def _full_name_spans(question_words, book):
    """Where the book's whole name (or the name without "The") appears
    in the question, as (start, end) word positions."""
    name = _words(book)
    names = [name] + ([name[1:]] if len(name) > 1 and name[0] == "the" else [])
    for n in names:
        for i in range(len(question_words) - len(n) + 1):
            if all(word_forms(q) & word_forms(w) for q, w in zip(question_words[i:i + len(n)], n)):
                yield i, i + len(n)


def _run_after(question_words, start, name_words):
    """The longest run of the book's name words (filler left out) that
    the question words from start on spell out in order, skipping the
    question's own filler words: "cooking for two" is a run of "The
    Complete Cooking For Two Cookbook". Returns (words matched, end)."""
    best = (0, start)
    for first in range(len(name_words)):
        i, j, matched, end = start, first, 0, start
        while i < len(question_words) and j < len(name_words):
            if question_words[i] in FILLER_WORDS:
                i += 1
                continue
            if not _same_word(question_words[i], name_words[j]):
                break
            matched, i, j, end = matched + 1, i + 1, j + 1, i + 1
        if matched > best[0]:
            best = (matched, end)
    return best


def find_books(question, books, title_words=frozenset()):
    """Books named in the question, and the question with those names
    taken out, so "...from 'The Book On Pie'" doesn't make the word "pie"
    count toward every pie title (that book has a recipe titled just
    "Pie"). A book is named by
        its full name, anywhere ("salt fat acid heat's lemon curd")
        its acronym, anywhere ("sfah"), unless the acronym is a word in
                some recipe title (title_words); an acronym two books
                share names both
        part of its name or a misspelling, after a word like "from"
                (BOOK_CUE_WORDS): "from dessert persn", "in food lab",
                "from cooking for two". At least two of its words, or the
                whole name for a one-word name ("from bravtart"). Only
                after a cue word, since "flour water" or "milk bar" in a
                question is more likely about ingredients than books.
    Where several books fit the same words, the one matching the most
    words is named ("from book on pie" is The Book On Pie, not The Cookie
    Book); a tie names them all."""
    words = _words(question)
    used = [False] * len(words)
    named = set()

    def take(book, start, end):
        named.add(book)
        for i in range(start, end):
            used[i] = True

    for book in books:
        for start, end in _full_name_spans(words, book):
            take(book, start, end)
        for acronym in book_acronyms(book) - set(title_words):
            for i, w in enumerate(words):
                if w == acronym:
                    take(book, i, i + 1)

    for i, w in enumerate(words):
        if w not in BOOK_CUE_WORDS or (i + 1 < len(words) and used[i + 1]):
            continue
        best, fits = 0, []
        for book in books:
            name_words = [x for x in _words(book) if x not in FILLER_WORDS]
            matched, end = _run_after(words, i + 1, name_words)
            if matched >= 2 or matched == len(name_words) >= 1:
                if matched > best:
                    best, fits = matched, [(book, end)]
                elif matched == best:
                    fits.append((book, end))
        for book, end in fits:
            take(book, i + 1, end)

    cleaned = " ".join(w for w, u in zip(words, used) if not u)
    return sorted(named), cleaned


def _score(candidate, question_forms, guess_forms):
    """The best-scoring of a candidate's searchable titles."""
    best = None
    for core, extra in candidate.variants:
        named_core = sum(1 for w in core if word_forms(w) & question_forms)
        named_extra = sum(1 for w in extra if word_forms(w) & question_forms)
        guess = sum(1 for w in core + extra if word_forms(w) & guess_forms)
        full = named_core == len(core)
        s = Scored(candidate, named_core + named_extra, guess, len(core) + len(extra),
                   full, full and named_extra == len(extra), named_extra)
        if best is None or (s.full, s.guess, s.score, s.exact) > (best.full, best.guess, best.score, best.exact):
            best = s
    return best


def _question_forms(words, vocabulary):
    """The word forms a question's words stand for, and the typos read
    as title words along the way."""
    forms, typos = set(), {}
    for q in words:
        q_forms = word_forms(q)
        forms |= q_forms
        if q_forms & vocabulary.keys():
            continue
        limit = typo_limit(q)
        if not limit:
            continue
        # Same first letter: typos are rarely there, and it keeps
        # unrelated words of the same length apart.
        close = {w for form, w in vocabulary.items()
                 if form[0] == q[0] and _edit_distance(q, form, limit) <= limit}
        if close:
            typos[q] = sorted(close)
            for w in close:
                forms |= word_forms(w)
    return forms, typos


def lookup(question, candidates, nearby=None):
    """Which candidates the question names. See the module docstring.

    nearby, when given, is {candidate key: rank} from the vector search
    (0 = the closest chunk), used to order titles that match equally
    well, so "scale the brownies, I only have 2 eggs" lists brownies
    before egg dishes."""
    nearby = nearby or {}
    title_words = {form for c in candidates for core, extra in c.variants
                   for w in core + extra for form in word_forms(w)}
    named_books, cleaned = find_books(question, {c.book for c in candidates}, title_words)
    if named_books:
        in_named = [c for c in candidates if c.book in named_books]
        # A book named in passing that has none of these recipes doesn't
        # rule the others out.
        candidates = in_named or candidates

    vocabulary = {}
    for c in candidates:
        for core, extra in c.variants:
            for w in core + extra:
                for form in word_forms(w):
                    vocabulary.setdefault(form, w)

    words = list(dict.fromkeys(title_tokens(cleaned)))
    question_forms, typos = _question_forms(words, vocabulary)
    guess_forms, _ = _question_forms([w for w in words if w not in REQUEST_WORDS], vocabulary)

    def order(scored):
        # Exact titles first, then the ones with the fewest words the
        # question didn't name (the most direct match), then the closest
        # by vector search, then by book and title so the order never
        # changes between runs.
        return sorted(scored, key=lambda s: (not s.exact, s.total - s.score,
                                             nearby.get(s.candidate.key, len(nearby)),
                                             s.candidate.book, s.candidate.title))

    def result(kind, ordered):
        return LookupResult(kind, [s.candidate for s in ordered[:MAX_LISTED]],
                            max(0, len(ordered) - MAX_LISTED), typos, named_books)

    scored = [s for s in (_score(c, question_forms, guess_forms) for c in candidates) if s and s.guess > 0]
    if not scored:
        return result("none", [])
    best = max(s.guess for s in scored)

    named = [s for s in scored if s.full and s.guess == best]
    if named:
        # Request words only break a tie: "double the double chocolate
        # cake" names "Double Chocolate Cake" over "Chocolate Cake".
        top = max(s.score for s in named)
        named = [s for s in named if s.score == top]
        # "pasta with mushrooms": "Pasta with Mushrooms" is named in full,
        # "Pasta with Mushroom Ragu" only scores as well because its own
        # "with" words overlap. Without "with" words in the question
        # ("rice pudding cake"), a title with a "with" tail is as good a
        # match as one without.
        if any(s.exact and s.extra_named for s in named):
            named = [s for s in named if s.exact]
        return result("match", order(named))

    def worth_guessing(s):
        return s.guess >= PARTIAL_MIN_WORDS or 2 * s.guess >= s.total

    close = [s for s in scored if s.guess == best and worth_guessing(s)]
    if not close:
        return result("none", [])
    # The best titles the question names in full come first, though a
    # word it also used makes another title closer: in "how much butter
    # is in the banana bread", "Almond Butter Banana Bread" shares more
    # words, but "Banana Bread" is all there.
    full = [s for s in scored if s.full and worth_guessing(s)]
    top_full = [s for s in full if s.guess == max(f.guess for f in full)] if full else []
    return result("partial", order(top_full) + order(close))


def load_candidates(hits):
    """What to search: every recipe in the recipe index, or the
    retrieved recipe chunks when the index hasn't been built (built at
    the end of ingest, or by tools/build_recipe_index.py)."""
    from match_utils.recipe_index import load_index  # imported late: it pulls in the scale parsers
    entries = load_index()
    if entries:
        return candidates_from_index(entries), "index"
    return candidates_from_hits(hits), "retrieved chunks"


def find_recipes(question, hits):
    """lookup() over load_candidates(hits), with the hits' order breaking
    ties. Returns (LookupResult, where it searched)."""
    candidates, source = load_candidates(hits)
    nearby = {}
    for rank, h in enumerate(hits):
        if h.get("content_type") == "recipe":
            nearby.setdefault(h.get("recipe_id"), rank)
    return lookup(question, candidates, nearby), source
