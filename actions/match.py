"""
Find recipes from the ingredients you have. See match.py.
"""

from dataclasses import dataclass, field

from common import cli
from match_utils.matching import find_matches, load_staples, parse_have
from match_utils.recipe_index import load_index, load_ingredient_words
from match_utils.typos import TypoFixer
from match_utils.typos import describe as describe_typos

# How many recipes to list in each section before summarizing the rest.
SHOW_PER_SECTION = 15


@dataclass
class MatchResult:
    """What matching came to. kind is one of:
        "no_index"        the recipe index hasn't been built
        "no_ingredients"  no ingredients in the request
        "matches"         have (as searched, typos corrected), corrections
                          (match_utils.typos), assumptions (what a general
                          name was taken to mean, once each), and three
                          lists of find_matches() results: ready (makeable
                          now), from_scratch (makeable by making a
                          sub-recipe from pantry staples), missing_one
    staples is the pantry staples assumed on hand."""
    kind: str
    have: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    ready: list = field(default_factory=list)
    from_scratch: list = field(default_factory=list)
    missing_one: list = field(default_factory=list)
    staples: set = field(default_factory=set)


def run(text):
    index = load_index()
    if index is None:
        return MatchResult("no_index")

    have = parse_have(text)
    if not have:
        return MatchResult("no_ingredients")
    # Misspelled ingredients are corrected before anything else, and
    # said so first, so a typo never silently loses every match.
    staples = load_staples()
    have, corrections = TypoFixer(load_ingredient_words(entries=index), staples).fix(have)

    results = find_matches(index, have)
    # What a general name ("cream") was taken to mean, listed once rather
    # than under every recipe it applies to.
    assumptions = []
    for result in results:
        for note in result["assumptions"]:
            if note not in assumptions:
                assumptions.append(note)
    ready = [r for r in results if not r["missing"]]
    return MatchResult(
        "matches", have=have, corrections=corrections, assumptions=assumptions,
        ready=[r for r in ready if not r["from_scratch"]],
        # Makeable, but only by making a sub-recipe (a pie dough) entirely
        # from pantry staples: real work the person didn't mention.
        from_scratch=[r for r in ready if r["from_scratch"]],
        missing_one=[r for r in results if len(r["missing"]) == 1],
        staples=staples)


# ---- the command line's text ------------------------------------------

def describe(result):
    entry = result["entry"]
    lines = [f"  {entry['title']}  [{entry['book']}"
             + (f", p.{entry['page']}" if entry["page_confirmed"] else "") + "]"]
    lines.append(f"      uses: {', '.join(result['uses'])}")
    if result.get("stand_ins"):
        lines.append(f"      using {'; '.join(result['stand_ins'])}")
    if result.get("makes"):
        scratch = set(result.get("from_scratch", []))
        lines.append("      make first: " + ", ".join(
            f"{name} (from pantry staples)" if name in scratch else name for name in result["makes"]))
    if result["missing"]:
        lines.append(f"      missing: {', '.join(result['missing'])}")
    # Unlinked sub-recipes are counted in "missing" now; only the
    # placeholders that can't be matched are shown on their own.
    also = [f"{name} (your choice)" for name in entry.get("your_choice", [])]
    if also:
        lines.append(f"      also needs: {'; '.join(also)}")
    if cli.DEBUG:
        lines.append(f"      [debug] staples: {', '.join(result['staples_used']) or '(none)'}"
                     f"  optional on hand: {', '.join(result['optional_on_hand']) or '(none)'}")
    return lines


def section_lines(heading, results):
    lines = [f"\n{heading} ({len(results)}):"]
    if not results:
        lines.append("  (none)")
    for result in results[:SHOW_PER_SECTION]:
        lines += describe(result)
    if len(results) > SHOW_PER_SECTION:
        lines.append(f"  ...and {len(results) - SHOW_PER_SECTION} more")
    return lines


def render(result):
    """The result as the command line shows it."""
    if result.kind == "no_index":
        return ("No recipe index yet. Run python3 ingest.py, or python3 tools/build_recipe_index.py "
                "if the database already exists.")
    if result.kind == "no_ingredients":
        return "List the ingredients you have, separated by commas."
    lines = [describe_typos(result.corrections)] if result.corrections else []
    lines.append(f"You have: {', '.join(result.have)}  (plus pantry staples)")
    if cli.DEBUG:
        lines.append(f"[debug] staples: {', '.join(sorted(result.staples))}")
    lines += [f"  ({note})" for note in result.assumptions]
    lines += section_lines("You can make", result.ready)
    lines += section_lines("You can make, with a sub-recipe from scratch", result.from_scratch)
    lines += section_lines("Missing one thing", result.missing_one)
    return "\n".join(lines)
