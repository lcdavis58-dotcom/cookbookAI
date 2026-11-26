"""
Filter recipes by an ingredient: "do any of these use half and half",
"a pumpkin pie without half and half", "a whipped cream that uses
chocolate". Answered from the recipe index (match_utils/uses.py), with no
model call.

"Uses X" lists the recipes that use it, with a note where it isn't plain
("bittersweet chocolate", "in All-Buttah Pie Dough", "optional"), then how
many don't. "Without X" lists only the ones that don't, including the
ones that can do without it ("it can use heavy cream instead").

The result is an ask.AskResult, so the chat numbers it, remembers it and
lets her pick from it like any other list of recipes.
"""

from actions.ask import AskResult
from match_utils.matching import parse_have
from match_utils.uses import Uses

# Shown at once. Past this many, the chat asks her to narrow it down.
SHOW_AT_ONCE = 30


def _plural(n, word="recipe"):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _without_note(use, typed):
    """Why a recipe that has the ingredient still counts as without it."""
    if use.optional:
        return f"the {typed} is optional"
    others = [o for o in use.instead if not o.startswith(("another ", "store-bought "))]
    swaps = [o for o in use.instead if o.startswith(("another ", "store-bought "))]
    if others:
        return f"it can use {' or '.join(others)} instead"
    where = f" in {use.where}" if use.where else ""
    return f"it has {typed}{where}, but {' or '.join(swaps)} works" if swaps else ""


def run(recipes, ingredient, without=False, what="", index=None, question="", every=False):
    """recipes: title_lookup.Candidates (the list on screen, or a dish's
    recipes). what names them for the reply ("pumpkin pie"); empty for
    the last list ("these"). every: recipes is every recipe, so the
    reply says "12 recipes use ..." with no count of the others.
    index: every index entry, to follow sub-recipes (default: the
    candidates' own)."""
    typed = " ".join(ingredient.split())
    names = parse_have(typed)
    name = names[0] if names else typed.lower()
    uses = Uses(index if index is not None else [c.payload for c in recipes if c.payload])
    found = [(c, uses.find(c.payload or {}, name)) for c in recipes]
    with_it = [(c, u) for c, u in found if u]
    kept = ([(c, u) for c, u in found if u is None or not u.needed] if without else with_it)

    count = len(kept)
    if what or every:
        some = _plural(count, f"{what} recipe" if what else "recipe")
    else:
        some = "this one" if len(recipes) == 1 else f"{count} of these"
    if not kept:
        if without:
            text = (f"That one uses {typed}." if len(recipes) == 1
                    else f"All {_plural(len(recipes), f'{what} recipe')} use {typed}." if what
                    else f"All {len(recipes)} of these use {typed}.")
        else:
            text = (f"None of your {what} recipes use {typed}." if what
                    else f"None of your recipes use {typed}." if every else f"None of these use {typed}.")
        return AskResult("said", question, heading=text)

    footer = ""
    if without:
        notes = {c.key: _without_note(u, typed) for c, u in kept if u}
        heading = (f"{some} without {typed}:" if what
                   else f"None of these use {typed}:" if count == len(recipes)
                   else f"{some} {'doesn' if count == 1 else 'don'}'t use {typed}:")
    else:
        notes = {c.key: u.note(name) for c, u in kept}
        heading = f"{some} {'uses' if count == 1 else 'use'} {typed}:"
        left = len(recipes) - count
        if left and not what and not every:
            footer = f"The other {left} {'doesn' if left == 1 else 'don'}'t."
    choices = [c for c, _ in kept]
    return AskResult("choices", question, choices=choices[:SHOW_AT_ONCE], rest=choices[SHOW_AT_ONCE:],
                     more=len(choices[SHOW_AT_ONCE:]), heading=heading, footer=footer,
                     notes={k: v for k, v in notes.items() if v})
