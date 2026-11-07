"""
Correcting misspelled ingredients before matching ("cinamon" ->
"cinnamon", "brown suger" -> "brown sugar"), word by word, against the
words the recipe index's ingredients use (counted when the index is
saved, recipe_index.ingredient_words) and the pantry staples.

The same caution as recipe title typos (query_utils/title_lookup.py):
    only words of 5+ letters, with the same first letter, one letter
    wrong (two from 8 letters on, see typo_limit)
    a word the index already uses, as typed or as a plural, is never
    changed, so a real ingredient isn't turned into another
    when two words are as close, the one more recipes use wins, and
    the other is named in the correction
Every correction is reported, so the person can see what was searched.
A word typed without its accents ("gruyere", "creme fraiche") isn't a
typo: it's given the index's spelling without a note.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from query_utils.title_lookup import edit_distance, typo_limit, word_forms


def _unaccented(word):
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


@dataclass
class Correction:
    typed: str              # the word as typed
    word: str               # what it was read as
    others: list = field(default_factory=list)   # other words as close


class TypoFixer:
    def __init__(self, word_counts, extra_words=()):
        """word_counts: {word: recipes using it}; extra_words: more known
        words (the pantry staples), counted as used once."""
        self.counts = dict(word_counts)
        for name in extra_words:
            for w in re.findall(r"[^\W\d_]+", name.lower()):
                self.counts.setdefault(w, 1)
        self.forms = {form for w in self.counts for form in word_forms(w)}
        # Unaccented spelling -> the index's own, most used first.
        self.accented = {}
        for w, _ in sorted(self.counts.items(), key=lambda kv: -kv[1]):
            if _unaccented(w) != w:
                self.accented.setdefault(_unaccented(w), w)

    def accent(self, word):
        """The index's accented spelling of a word typed without its
        accents ("gruyere" -> "gruyère"), or None. Not a typo, so it's
        put right without a note."""
        if word in self.counts:
            return None
        return self.accented.get(_unaccented(word))

    def fix_word(self, word):
        """A Correction for one word, or None when it's known or nothing
        is close enough."""
        if word_forms(word) & self.forms or self.accent(word):
            return None
        limit = typo_limit(word)
        if not limit:
            return None
        close = []
        for known, count in self.counts.items():
            if known[0] != word[0]:
                continue
            distance = edit_distance(word, known, limit)
            if distance <= limit:
                close.append((distance, -count, known))
        if not close:
            return None
        close.sort()
        best = close[0]
        others = [k for d, c, k in close[1:] if d == best[0]]
        return Correction(word, best[2], others)

    def fix(self, names):
        """(names with misspelled words corrected, [Correction]). Names
        keep their order; a correction that makes a name repeat an
        earlier one drops it."""
        fixed, corrections = [], []
        for name in names:
            words = name.split()
            for i, w in enumerate(words):
                bare = w.strip("-'’")
                if not bare.isalpha():
                    continue
                accented = self.accent(bare)
                if accented:
                    words[i] = w.replace(bare, accented)
                    continue
                correction = self.fix_word(bare)
                if correction:
                    words[i] = w.replace(bare, correction.word)
                    if all(c.typed != correction.typed for c in corrections):
                        corrections.append(correction)
            name = " ".join(words)
            if name not in fixed:
                fixed.append(name)
        return fixed, corrections


def describe(corrections):
    """The note match.py prints first, saying what was taken for a typo
    and searched for instead."""
    def read_as(c):
        others = " (or " + ", ".join(f'"{o}"' for o in c.others) + ")" if c.others else ""
        return f'"{c.word}"{others}'

    if len(corrections) == 1:
        c = corrections[0]
        return f'Note: "{c.typed}" looks like a typo, so I searched for {read_as(c)} instead.'
    return ("Note: these look like typos, so I searched for the corrected names instead: "
            + ", ".join(f'"{c.typed}" -> {read_as(c)}' for c in corrections) + ".")
