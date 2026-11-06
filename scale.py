"""
Scale a recipe up, down, or to fit an ingredient constraint.

Run:
    python3 scale.py "please double the classic whipped cream recipe"
    python3 scale.py "the chocolate whipped cream feeds 6, I need 10"
    python3 scale.py "classic whipped cream needs 2 eggs, I only have 1"
    python3 scale.py -d "double the sweet tart dough"    # with debug output

Where things live:
    query_utils/                     finding the recipe (shared with query.py),
                                     by title in query_utils/title_lookup.py
    scale_utils/ingredients.py       ingredient list -> groups (all books)
    books/<book>.py           each book's ingredient line format
    scale_utils/recipe_scaling.py    scale factor from the request, the math
    scale_utils/pan_scaling.py       pan-size scale factors
    scale_utils/measurement_display.py  amounts -> real measuring tools
    scale_utils/scaling_rules.py     non-scalable / storage-sensitive notes

Requires the same packages/models as query.py, plus a chat model that
supports tool calling (llama3.2:1b does).
"""

from common import cli
from books import strategy_for
from query_utils.recipe_matching import display_title, extract_title, extract_yield_line
from query_utils.retrieval import candidate_text, retrieve, within_distance
from query_utils.title_lookup import find_recipes
from scale_utils.ingredients import extract_ingredient_groups, pick_default_batch
from scale_utils.measurement_display import count_unit_label, format_imperial_amount, to_teaspoons
from scale_utils.pan_scaling import detect_pan_request, pan_scale_factor_from_question
from scale_utils.recipe_scaling import (detect_direct_multiplier, determine_scale_intent,
                                        resolve_scale_factor, scale_ingredients)


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


def print_scaled_ingredient(ing):
    if ing["unmeasured"]:
        # "Butter for the pan", "Egg wash": no amount to scale.
        print(f"  {ing['name']}  (as needed, not scaled)")
        return

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

    print(f"  {ing['name']}: {orig}  ->  {scaled}")
    for flag_type, note in ing["flags"]:
        marker = "[!]" if flag_type == "non_scalable" else "[i]"
        print(f"      {marker} {note}")


def print_choices(found):
    for i, c in enumerate(found.matches, 1):
        print(f"  {i}. {c.title}  ({c.book})")
    if found.more:
        print(f"  ...and {found.more} more. Add more of the recipe's name to narrow it down.")
    if len({c.book for c in found.matches}) > 1:
        print(f'\nNaming the book picks between them, e.g. '
              f'"... the {found.matches[0].title.lower()} from {found.matches[0].book}".')


def scale_recipe(question):
    hits = retrieve(question)
    found, source = find_recipes(question, hits)
    if cli.DEBUG:
        print(f"[debug] title lookup in the {source}: {found.kind}, "
              f"{len(found.matches) + found.more} title(s), typos read as {found.typos or '(none)'}, "
              f"books named: {found.books or '(none)'}")

    if found.kind == "none":
        if found.books:
            print(f"I couldn't find a recipe by that name in {' or '.join(found.books)}.")
            print("Check the recipe's name, or leave the book out to search every book.")
            return
        if not within_distance(hits):
            print("I couldn't find anything relevant to that in your cookbooks.")
            return
        print("I couldn't identify a specific recipe to scale from your request.")
        print('Try including the recipe name, e.g. "double the classic whipped cream recipe".')
        return

    if found.kind == "partial":
        print("I couldn't find a recipe by exactly that name. Did you mean one of these?\n")
        print_choices(found)
        print("\nRun again using one of these names.")
        return

    if len(found.matches) > 1:
        total = len(found.matches) + found.more
        print(f"I found {total} recipes matching your request. Which one did you mean?\n")
        print_choices(found)
        return

    match = found.matches[0]
    recipe_text = candidate_text(match)
    if not recipe_text:
        print(f"Found '{match.title}' in the recipe index, but it isn't in the database. "
              f"The index is out of date: run tools/build_recipe_index.py.")
        return
    title = display_title(extract_title(recipe_text, match.book))

    strategy = strategy_for(match.book)
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
    batch_note = ""
    batches = groups.batches
    if batches:
        batch_name = pick_default_batch({name: groups[name] for name in batches})
        if batch_name is None:
            print(f"'{title}' has multiple batch sizes and no single default. Which one do you want?\n")
            for name in batches:
                description = groups.descriptions.get(name)
                print(f"  - {name}" + (f" ({description})" if description else ""))
            return
        batch_note = f" ({batch_name})"
        sections = {name: ings for name, ings in groups.items()
                    if name == batch_name or name not in batches}
    else:
        sections = dict(groups)
    show_section_headers = len(sections) > 1

    ingredients = [ing for section in sections.values() for ing in section]
    if not ingredients:
        print(f"Found '{title}' but couldn't parse any ingredients from it, "
              f"this may need a parser update.")
        return

    yield_line = extract_yield_line(recipe_text)
    print(f"Scaling '{title}'{batch_note} from {match.book}...\n")

    # Try deterministic pre-checks first, in order of how unambiguous
    # they are. Unambiguous multiplier phrasing ("double", "3x") and
    # pan-size requests never need to go anywhere near the model.
    direct_factor = detect_direct_multiplier(question)
    if direct_factor is not None:
        factor, explanation = direct_factor, f"Direct multiplier (detected in question text): {direct_factor}x"
    elif detect_pan_request(question):
        factor, explanation = pan_scale_factor_from_question(question)
        if factor is None:
            print(f"Couldn't resolve a pan-size scale factor: {explanation}")
            return
    else:
        intent, elapsed = determine_scale_intent(question, title, yield_line, ingredients)
        if cli.DEBUG:
            print(f"[debug] model call took {elapsed:.2f}s")
        if intent is None:
            print("I couldn't determine how you want to scale this recipe.")
            print('Try rephrasing, e.g. "double it" or "scale it for 10 people".')
            return

        if cli.DEBUG:
            print(f"[debug] raw model intent: {intent}\n")
        factor, explanation = resolve_scale_factor(intent, ingredients)

    if factor == "ambiguous":
        print(f"That ingredient matches more than one item in this recipe: {', '.join(explanation)}")
        print("Try being more specific about which one you mean.")
        return

    if factor is None:
        print(f"Couldn't resolve a scale factor: {explanation}")
        return

    print(f"{explanation}\n")

    for section_name, section_ingredients in sections.items():
        if not section_ingredients:
            continue
        if show_section_headers:
            # "default" holds the ingredients before the first label.
            heading = "Base" if section_name == "default" else section_name
            optional = " (optional)" if groups.kinds.get(section_name) == "optional" else ""
            print(f"{heading}{optional}:")
        for ing in scale_ingredients(section_ingredients, factor):
            print_scaled_ingredient(ing)


if __name__ == "__main__":
    request, cli.DEBUG = cli.parse_cli("Scale a recipe from your ingested cookbooks.")
    scale_recipe(request)
