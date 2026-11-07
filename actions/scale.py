"""
Scale a recipe: find the recipe a request names (find), then scale it
(scale_recipe). run() does both. See scale.py.

scale_recipe takes a recipe that's already been found, so a follow-up
("now halve it") can scale the same recipe again without naming it. Its
base is the factor the recipe is already at: a multiplier ("halve it")
builds on it, while a target yield ("for 12 people"), an ingredient
limit ("I only have 1 egg") or a pan size names the end result, so it's
worked out from the recipe as written.
"""

import re
from dataclasses import dataclass, field

from common import cli
from books import strategy_for
from query_utils.recipe_matching import display_title, extract_title, extract_yield_line
from query_utils.retrieval import candidate_text, retrieve, within_distance
from query_utils.title_lookup import find_recipes, title_tokens
from scale_utils.ingredients import extract_ingredient_groups, pick_default_batch
from scale_utils.measurement_display import count_unit_label, format_imperial_amount, to_teaspoons
from scale_utils.pan_scaling import detect_pan_request, pan_scale_factor_from_question
from scale_utils.recipe_scaling import (MAX_SANE_FACTOR, MIN_SANE_FACTOR, detect_direct_multiplier,
                                        determine_scale_intent, normalize_basis, resolve_scale_factor,
                                        scale_ingredients)


@dataclass
class Section:
    """One group of a scaled recipe's ingredients. heading is None when
    the recipe has only one group (no heading is shown)."""
    heading: str
    optional: bool
    ingredients: list               # scale_ingredients() output


@dataclass
class ScaleResult:
    """What scaling a request came to. kind is one of:
        "not_found"       no recipe identified; reason is "not_in_book"
                          (books names the books searched), "nothing_relevant"
                          or "no_recipe"
        "choices"         several recipes might be meant: choices, more,
                          partial (True when none is named in full, a
                          "Did you mean")
        "stale_index"     the recipe is in the index but not the database
        "no_ingredients"  found, but no ingredients could be parsed
        "pick_batch"      several batch sizes and no default: batches,
                          as (name, description or None)
        "no_factor"       found, but no scale factor: problem is "pan",
                          "no_intent", "ambiguous" (ambiguous lists the
                          ingredients it could mean) or "unresolved", with
                          explanation saying why
        "scaled"          factor, explanation, sections
    recipe is the title_lookup.Candidate once one was found; title,
    book and batch (the batch size scaled, or "") are filled in from
    "no_ingredients" on."""
    kind: str
    recipe: object = None
    title: str = ""
    book: str = ""
    batch: str = ""
    reason: str = ""
    books: list = field(default_factory=list)
    choices: list = field(default_factory=list)
    more: int = 0
    partial: bool = False
    batches: list = field(default_factory=list)
    problem: str = ""
    ambiguous: list = field(default_factory=list)
    factor: float = None
    explanation: str = ""
    sections: list = field(default_factory=list)
    # The model's scale intent, when it was asked (shown with -d).
    intent: dict = None
    model_time: float = None


def find(question):
    """The recipe a scaling request names: (Candidate, None) when it
    names exactly one, else (None, ScaleResult) saying why not."""
    hits = retrieve(question)
    found, source = find_recipes(question, hits)
    if cli.DEBUG:
        print(f"[debug] title lookup in the {source}: {found.kind}, "
              f"{len(found.matches) + found.more} title(s), typos read as {found.typos or '(none)'}, "
              f"books named: {found.books or '(none)'}")

    if found.kind == "none":
        if found.books:
            return None, ScaleResult("not_found", reason="not_in_book", books=found.books)
        if not within_distance(hits):
            return None, ScaleResult("not_found", reason="nothing_relevant")
        return None, ScaleResult("not_found", reason="no_recipe")
    if found.kind == "partial" or len(found.matches) > 1:
        return None, ScaleResult("choices", choices=found.matches, more=found.more,
                                 partial=found.kind == "partial")
    return found.matches[0], None


def run(question):
    recipe, problem = find(question)
    return problem or scale_recipe(recipe, without_title_multipliers(question, recipe))


def without_title_multipliers(question, recipe):
    """The request with the multiplier words the recipe's own title uses
    taken out once each, so "scale the double chocolate cake for 12"
    isn't read as "double", while "double the double chocolate cake"
    still is."""
    for word in title_tokens(recipe.title):
        if detect_direct_multiplier(word) is not None:
            question = re.sub(rf"\b{re.escape(word)}\b", " ", question, count=1, flags=re.IGNORECASE)
    return " ".join(question.split())


def find_batch(text, batch_names):
    """The batch size a message names ("mile high", "the full one"), by
    the words of its name other than "batch"; None unless exactly one
    fits best."""
    said = set(title_tokens(text))
    best, fits = 0, []
    for name in batch_names:
        shared = len(said & (set(title_tokens(name)) - {"batch"}))
        if shared > best:
            best, fits = shared, [name]
        elif shared == best and shared:
            fits.append(name)
    return fits[0] if len(fits) == 1 else None


def times(value):
    return f"{format_amount(round(value, 3))}x"


def scale_recipe(recipe, question, base=1.0, batch=None, factor=None, explanation=None):
    """Scale a found recipe (a title_lookup.Candidate) as the request
    asks. base: the factor it's already at, which a multiplier builds on.
    batch: the batch size to use, by name (find_batch), instead of the
    default one. factor (with explanation): use this factor as is, for
    switching batch sizes at the current factor or going back to the
    recipe as written."""
    recipe_text = candidate_text(recipe)
    if not recipe_text:
        return ScaleResult("stale_index", recipe=recipe, title=recipe.title, book=recipe.book)
    title = display_title(extract_title(recipe_text, recipe.book))
    found = dict(recipe=recipe, title=title, book=recipe.book)

    strategy = strategy_for(recipe.book)
    groups = extract_ingredient_groups(recipe_text, strategy)

    if cli.DEBUG:
        print(f"[debug] ingredient rules: {strategy}, groups: {list(groups) or '(none)'}")
        for name, ings in groups.items():
            for ing in ings:
                print(f"[debug]   {name}: {ing['raw']!r}")
        print()

    # Batch groups are alternative sizes (Book on Pie's Half, Full,
    # Mile-High), only one of which gets made, so exactly one is picked.
    # Every other group is a component (a Filling, a Glaze, the
    # ingredients before any label) and is always scaled along with it.
    batch_name = ""
    batches = groups.batches
    if batches:
        batch_name = (find_batch(batch, batches) if batch else None) or             pick_default_batch({name: groups[name] for name in batches})
        if batch_name is None:
            return ScaleResult("pick_batch", **found,
                               batches=[(name, groups.descriptions.get(name)) for name in batches])
        chosen = {name: ings for name, ings in groups.items()
                  if name == batch_name or name not in batches}
    else:
        chosen = dict(groups)
    found["batch"] = batch_name

    ingredients = [ing for section in chosen.values() for ing in section]
    if not ingredients:
        return ScaleResult("no_ingredients", **found)

    yield_line = extract_yield_line(recipe_text)

    # Try deterministic pre-checks first, in order of how unambiguous
    # they are. Unambiguous multiplier phrasing ("double", "3x") and
    # pan-size requests never need to go anywhere near the model.
    intent = elapsed = None
    relative = None                 # the multiplier, when it builds on base
    direct_factor = detect_direct_multiplier(question)
    if factor is not None:
        pass
    elif direct_factor is not None:
        factor, explanation = direct_factor, f"Direct multiplier (detected in question text): {direct_factor}x"
        relative = direct_factor
    elif detect_pan_request(question):
        factor, explanation = pan_scale_factor_from_question(question)
        if factor is None:
            return ScaleResult("no_factor", **found, problem="pan", explanation=explanation)
    else:
        intent, elapsed = determine_scale_intent(question, title, yield_line, ingredients)
        if intent is None:
            return ScaleResult("no_factor", **found, problem="no_intent", model_time=elapsed)
        factor, explanation = resolve_scale_factor(intent, ingredients, yield_line, question)
        if normalize_basis(intent) == "direct" and isinstance(factor, float):
            relative = factor
    model = dict(intent=intent, model_time=elapsed)

    if relative is not None and base != 1:
        factor = base * relative
        explanation = f"{times(relative)} the {times(base)} version = {times(factor)} the recipe as written"
        if not MIN_SANE_FACTOR <= factor <= MAX_SANE_FACTOR:
            return ScaleResult("no_factor", **found, **model, problem="unresolved",
                               explanation=f"{explanation}, which is outside the range I'll scale to")

    if factor == "ambiguous":
        return ScaleResult("no_factor", **found, **model, problem="ambiguous", ambiguous=explanation)
    if factor is None:
        return ScaleResult("no_factor", **found, **model, problem="unresolved", explanation=explanation)

    show_headings = len(chosen) > 1
    sections = []
    for name, section_ingredients in chosen.items():
        if not section_ingredients:
            continue
        # "default" holds the ingredients before the first label.
        heading = ("Base" if name == "default" else name) if show_headings else None
        sections.append(Section(heading, groups.kinds.get(name) == "optional",
                                scale_ingredients(section_ingredients, factor)))
    return ScaleResult("scaled", **found, **model, factor=factor, explanation=explanation, sections=sections)


# ---- the command line's text ------------------------------------------

def format_amount(value):
    """1.0 -> "1", 1.5 -> "1.5", trims trailing zeros without leaving an
    ugly "1." behind."""
    if value is None:
        return None
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_side(amount, unit, rounded=False):
    if not amount:
        return None
    prefix = "~" if rounded else ""
    return f"{prefix}{format_amount(amount)} {unit or ''}".strip()


def scaled_ingredient_lines(ing):
    if ing["unmeasured"]:
        # "Butter for the pan", "Egg wash": no amount to scale.
        return [f"  {ing['name']}  (as needed, not scaled)"]

    # A compound amount ("3 tablespoons plus 1/3 cup") is stored as one
    # number in its larger unit, show the book's own wording instead.
    imperial_unit = ing["imperial_unit"]
    if to_teaspoons(1, imperial_unit) is None:
        # Not a volume unit: a stick count or a bare count, label it the
        # same way the scaled side will ("1 stick", "1 whole").
        imperial_unit = count_unit_label(ing["original_imperial"], imperial_unit)
    orig_imperial = (ing.get("original_imperial_display")
                     or format_side(ing["original_imperial"], imperial_unit))
    orig = " / ".join(filter(None, [
        format_side(ing["original_metric"], ing["metric_unit"]),
        orig_imperial,
    ]))

    metric_str = format_side(ing["scaled_metric"], ing["metric_unit"], ing.get("scaled_metric_rounded"))

    imperial_str = None
    if ing["scaled_imperial"]:
        # Volume units (teaspoon/tablespoon/cup) get decomposed into a
        # sensible combination of real measuring tools rather than one
        # large or awkward number. Non-volume imperial units (ounces,
        # bare counts) fall back to plain rounding inside this function.
        imp_display, imp_rounded = format_imperial_amount(ing["scaled_imperial"], ing["imperial_unit"])
        imperial_str = f"{'~' if imp_rounded else ''}{imp_display}"

    scaled = " / ".join(filter(None, [metric_str, imperial_str]))

    # "scant 1 g" scales to "scant 2 g": the hedge stays with the amount.
    if ing["qualifier"]:
        orig, scaled = f"{ing['qualifier']} {orig}", f"{ing['qualifier']} {scaled}"

    lines = [f"  {ing['name']}: {orig}  ->  {scaled}"]
    for flag_type, note in ing["flags"]:
        marker = "[!]" if flag_type == "non_scalable" else "[i]"
        lines.append(f"      {marker} {note}")
    return lines


def choice_lines(result):
    lines = [f"  {i}. {c.title}  ({c.book})" for i, c in enumerate(result.choices, 1)]
    if result.more:
        lines.append(f"  ...and {result.more} more. Add more of the recipe's name to narrow it down.")
    if len({c.book for c in result.choices}) > 1:
        first = result.choices[0]
        lines.append(f'\nNaming the book picks between them, e.g. '
                     f'"... the {first.title.lower()} from {first.book}".')
    return lines


NOT_FOUND = {
    "nothing_relevant": ["I couldn't find anything relevant to that in your cookbooks."],
    "no_recipe": ["I couldn't identify a specific recipe to scale from your request.",
                  'Try including the recipe name, e.g. "double the classic whipped cream recipe".'],
}


def render(result):
    """The result as the command line shows it."""
    kind = result.kind
    if kind == "not_found":
        if result.reason == "not_in_book":
            return "\n".join([f"I couldn't find a recipe by that name in {' or '.join(result.books)}.",
                              "Check the recipe's name, or leave the book out to search every book."])
        return "\n".join(NOT_FOUND[result.reason])
    if kind == "choices":
        if result.partial:
            return "\n".join(["I couldn't find a recipe by exactly that name. Did you mean one of these?\n",
                              *choice_lines(result), "\nRun again using one of these names."])
        total = len(result.choices) + result.more
        return "\n".join([f"I found {total} recipes matching your request. Which one did you mean?\n",
                          *choice_lines(result)])
    if kind == "stale_index":
        return (f"Found '{result.title}' in the recipe index, but it isn't in the database. "
                f"The index is out of date: run tools/build_recipe_index.py.")
    if kind == "pick_batch":
        lines = [f"'{result.title}' has multiple batch sizes and no single default. Which one do you want?\n"]
        lines += [f"  - {name}" + (f" ({description})" if description else "")
                  for name, description in result.batches]
        return "\n".join(lines)
    if kind == "no_ingredients":
        return (f"Found '{result.title}' but couldn't parse any ingredients from it, "
                f"this may need a parser update.")

    batch_note = f" ({result.batch})" if result.batch else ""
    lines = [f"Scaling '{result.title}'{batch_note} from {result.book}...\n"]
    if cli.DEBUG and result.model_time is not None:
        lines.append(f"[debug] model call took {result.model_time:.2f}s")
    if cli.DEBUG and result.intent is not None:
        lines.append(f"[debug] raw model intent: {result.intent}\n")

    if kind == "no_factor":
        if result.problem == "pan":
            lines.append(f"Couldn't resolve a pan-size scale factor: {result.explanation}")
        elif result.problem == "no_intent":
            lines += ["I couldn't determine how you want to scale this recipe.",
                      'Try rephrasing, e.g. "double it" or "scale it for 10 people".']
        elif result.problem == "ambiguous":
            lines += [f"That ingredient matches more than one item in this recipe: {', '.join(result.ambiguous)}",
                      "Try being more specific about which one you mean."]
        else:
            lines.append(f"Couldn't resolve a scale factor: {result.explanation}")
        return "\n".join(lines)

    lines.append(f"{result.explanation}\n")
    for section in result.sections:
        if section.heading is not None:
            lines.append(f"{section.heading}{' (optional)' if section.optional else ''}:")
        for ing in section.ingredients:
            lines += scaled_ingredient_lines(ing)
    return "\n".join(lines)
