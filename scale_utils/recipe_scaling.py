"""
Recipe scaling.

Division of labor, deliberately:
  - The MODEL reads the question (plus the recipe's yield line and
    ingredient names, already-correct data from our own parser) and
    reports back WHAT KIND of scaling this is and the raw numbers
    involved. It never computes a ratio and never re-transcribes an
    ingredient amount, both are things we've already seen it get wrong.
  - PYTHON does every actual calculation: dividing to get the scale
    factor, multiplying ingredient amounts, matching ingredient names,
    checking the exception lists. All deterministic, all testable
    without ever calling the model.

A further refinement, learned from testing: even the "which basis"
classification wasn't fully reliable from a 1B model, it could populate
fields from multiple bases at once, none of them coherent (see
detect_direct_multiplier below). Where a pattern is unambiguous and
regular enough to catch with a plain regex, do that BEFORE ever
involving the model, rather than trusting a structured-output call to
get the easy case right.
"""

import math
import re

from common import models
from common.word_list_loader import load_universal
from scale_utils.measurement_display import to_teaspoons
from scale_utils.scaling_rules import check_ingredient_flags, whole_item

SCALE_INTENT_TOOL = {
    "type": "function",
    "function": {
        "name": "determine_scale_intent",
        "description": (
            "Determine how the user wants to scale a recipe, based on their "
            "request and the recipe's stated yield and ingredient list. "
            "Do NOT do any arithmetic, just identify which basis applies and "
            "report the raw numbers involved, exactly as stated. The actual "
            "scaling math happens elsewhere."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "basis": {
                    "type": "string",
                    "enum": ["direct", "yield", "ingredient_constraint"],
                    "description": (
                        "'direct': the user gave an explicit multiplier "
                        "(double, triple, half). 'yield': the user stated a "
                        "target serving/yield amount, and the recipe's own "
                        "yield line states the original. "
                        "'ingredient_constraint': the user described how "
                        "much of ONE specific ingredient they have, "
                        "different from what the recipe calls for."
                    ),
                },
                "direct_multiplier": {
                    "type": "number",
                    "description": "The multiplier, if basis is 'direct'. E.g. 2 for double, 0.5 for half. Omit otherwise.",
                },
                "target_yield": {
                    "type": "number",
                    "description": "The yield/servings the user wants, if basis is 'yield'. Omit otherwise.",
                },
                "original_yield": {
                    "type": "number",
                    "description": (
                        "The recipe's original yield, if basis is 'yield': the number the user gives for "
                        "it, if they give one ('it feeds 6, I need 10' -> 6); otherwise read from the "
                        "stated yield line, but only when it counts the same thing as the target (servings, "
                        "people, pieces). If the yield line only gives a weight or volume (grams, cups) and "
                        "the user asks for people or servings, omit this. Omit otherwise."
                    ),
                },
                "reference_ingredient": {
                    "type": "string",
                    "description": "The ingredient name the user's constraint is about, if basis is 'ingredient_constraint', matched to the closest name in the provided ingredient list (e.g. 'eggs'). Omit otherwise.",
                },
                "target_ingredient_amount": {
                    "type": "number",
                    "description": "The amount of that ingredient the user says they actually have, if basis is 'ingredient_constraint'. Omit otherwise.",
                },
            },
            "required": ["basis"],
        },
    },
}


def determine_scale_intent(question, recipe_title, yield_line, ingredients):
    """Ask the model to classify the scaling request. Returns
    (arguments_dict, elapsed_seconds), or (None, elapsed_seconds) if the
    model didn't use the tool. Timing is returned regardless of outcome,
    since "how long did that take" matters as much as "did it work" when
    comparing models (CHAT_MODEL in common/config.py).
    """
    ingredient_list_text = "\n".join(
        f"- {ing['name']}: as needed" if ing.get("unmeasured") else
        f"- {ing['name']}: {ing.get('qualifier') or ''} "
        f"{ing['metric_amount']} {ing['metric_unit'] or ''} "
        f"/ {ing.get('imperial_display') or ing['imperial_amount']} "
        f"{'' if ing.get('imperial_display') else ing['imperial_unit'] or ''}".strip()
        for ing in ingredients
    )

    system_prompt = (
        "You determine how a user wants to scale a recipe. You will be "
        "given the recipe's title, its stated yield line, and its parsed "
        "ingredient list with amounts already correct. Call "
        "determine_scale_intent with the right basis and the raw numbers "
        "involved. Never compute a ratio, multiply, or divide, just "
        "identify and report the numbers as stated, the math is handled "
        "separately."
    )
    user_prompt = (
        f"Recipe: {recipe_title}\n"
        f"Stated yield: {yield_line}\n"
        f"Ingredients:\n{ingredient_list_text}\n\n"
        f"User request: {question}"
    )

    response, elapsed = models.chat(
        "scale intent",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=[SCALE_INTENT_TOOL],
        options={"temperature": 0.1},
    )

    tool_calls = response["message"].get("tool_calls")
    if not tool_calls:
        return None, elapsed
    return tool_calls[0]["function"]["arguments"], elapsed


_DEFAULT_MULTIPLIERS = {
    "double": 2.0, "doubled": 2.0, "doubling": 2.0,
    "triple": 3.0, "tripled": 3.0, "tripling": 3.0,
    "quadruple": 4.0, "quadrupled": 4.0,
    "half": 0.5, "halve": 0.5, "halved": 0.5, "halving": 0.5,
    "quarter": 0.25, "quartered": 0.25,
}


def detect_direct_multiplier(question):
    """Catch unambiguous multiplier phrasing ("double", "3x", "scale by
    2.5") with a plain regex, before ever involving the model. This isn't
    about avoiding one bug, it's the same principle as the ingredient
    parser: when a pattern is regular enough to detect deterministically,
    detecting it in code is strictly safer than trusting a small model's
    structured output to get it right, since code either matches or it
    doesn't, there's no "populated three incoherent fields at once" mode.
    Returns a float, or None if nothing unambiguous was found (in which
    case the request needs the model's judgment after all).
    """
    q = without_named_multipliers(question.lower())
    words = load_universal("direct_multipliers.json", {"words": _DEFAULT_MULTIPLIERS}).get("words", _DEFAULT_MULTIPLIERS)

    # "half again as much" is half as much again, 1.5x; checked before
    # the plain "half" below.
    if re.search(r"\bhalf\s+again\b", q):
        return 1.5

    for word, factor in words.items():
        if re.search(rf"\b{word}\b", q):
            return factor

    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:x|times)\b", q)
    if m:
        return float(m.group(1))

    # "scale by 3", "scale that by 3", "scale the recipe up by 3".
    # "scale it down by 3" is left to the model: a third, or 3 fewer?
    m = re.search(r"\bscaled?\s+(?:(?:it|that|this|them|the\s+recipe)\s+)?(?:up\s+)?by\s+(\d+(?:\.\d+)?)\b", q)
    if m:
        return float(m.group(1))

    return None


_DEFAULT_NOT_MULTIPLIERS = ["half and half", "half-and-half", "half & half", "double cream"]


def without_named_multipliers(text):
    """The text with names that contain a multiplier word but aren't one
    taken out (word_lists/universal/not_multipliers.json): "half and
    half" is cream, "a double boiler" is a pan."""
    phrases = load_universal("not_multipliers.json", {"phrases": _DEFAULT_NOT_MULTIPLIERS}).get(
        "phrases", _DEFAULT_NOT_MULTIPLIERS)
    for phrase in phrases:
        text = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", text, flags=re.IGNORECASE)
    return text


def normalize_basis(intent):
    """The model's reported "basis" field isn't always exactly one of our
    three enum values, e.g. it might return "direct_multiplier" (a field
    name) instead of "direct" (the actual enum value), a near-miss that
    still clearly signals the right intent. Rather than failing outright
    on anything that doesn't match exactly, infer the real basis from
    WHICH fields actually got filled in.

    Important: if fields from MORE THAN ONE basis are populated at once
    (seen in practice: yield fields AND ingredient fields both filled in
    for what was actually a simple "double it" request), that's not a
    tiebreak to resolve by picking one, it's a sign the model's response
    is internally inconsistent. Returns "conflicting" in that case rather
    than silently guessing, since a guess here has already produced a
    nonsense 0.005x scale factor once.
    """
    basis = intent.get("basis")
    if basis in ("direct", "yield", "ingredient_constraint"):
        return basis

    candidates = []
    if intent.get("direct_multiplier"):
        candidates.append("direct")
    if intent.get("target_yield") and intent.get("original_yield"):
        candidates.append("yield")
    if intent.get("reference_ingredient") and intent.get("target_ingredient_amount"):
        candidates.append("ingredient_constraint")

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return "conflicting"
    return basis  # nothing recognizable at all


MIN_SANE_FACTOR = 0.05  # scaling below 1/20th is almost certainly a misread, not a real request
MAX_SANE_FACTOR = 20    # scaling above 20x likewise


TRY_INSTEAD = 'Try "double it", "make it for 8", or how much of one ingredient you have ("I only have 2 eggs").'


def _check_sane(factor, explanation):
    """Reject an internally-plausible-looking but almost certainly wrong
    factor before it ever reaches the multiplication step. A model
    misreading a yield line's own two numbers as "before" and "after"
    (as happened in testing) produces a factor that passed every earlier
    check yet was still nonsense, this catches that class of failure.
    The refusal is worded for her; the -d flag shows the model's numbers.
    """
    if factor < MIN_SANE_FACTOR or factor > MAX_SANE_FACTOR:
        return None, (f"That works out to {factor:.3g} times the recipe, which is more likely a misreading than "
                      f"what you meant, so I didn't scale it. {TRY_INSTEAD}")
    return factor, explanation


_MEASURE_UNIT = r"(?:g|grams?|kg|ml|milliliters?|l|liters?|cups?|oz|ounces?|pounds?|lbs?|quarts?|pints?|" \
                r"tablespoons?|teaspoons?|tbsp|tsp)"
_NUM = r"\d+(?:[./]\d+)?[½¼¾⅓⅔]?"
# A run of numbers ("141, 283, or 422") followed by a weight or volume.
_MEASURE_RUN_RE = re.compile(rf"({_NUM}(?:\s*(?:,\s*)?(?:or|to|and|-|–|,)\s*{_NUM})*)\s*{_MEASURE_UNIT}\b",
                             re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def yield_measure_numbers(yield_line):
    """The numbers in a yield line that are weights or volumes, not
    counts: 141, 283 and 422 in "MAKES 141, 283, OR 422 G / 1, 3, OR 4
    CUPS", but not 6 in "Serves 6"."""
    numbers = set()
    for m in _MEASURE_RUN_RE.finditer(yield_line or ""):
        numbers.update(float(n) for n in _NUMBER_RE.findall(m.group(1)))
    return numbers


# What follows a number that isn't a count: a weight or volume, a size,
# a time, a temperature, a multiplier.
_NOT_A_COUNT_RE = re.compile(rf"\s*(?:-\s*)?(?:(?:{_MEASURE_UNIT}|inch(?:es)?|cm|x|min(?:ute)?s?|hours?|"
                             r"degrees?)\b|[\"%°])", re.IGNORECASE)
_COUNT_CANDIDATE_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


def count_numbers(question):
    """The numbers in a request that count something (people, servings,
    pieces): 5 and 8 in "this usually feeds 5 people, make it feed 8",
    but not 9 in "a 9-inch pan" or 200 in "200 g"."""
    return [float(m.group(1)) for m in _COUNT_CANDIDATE_RE.finditer(question or "")
            if not _NOT_A_COUNT_RE.match(question[m.end():])]


# How much the recipe makes, as she says it: "it usually feeds 5", "this
# serves 8", "the recipe makes 12". Only the -s forms: "make it feed 8"
# is the target, not the original.
_ORIGINAL_YIELD_RE = re.compile(r"\b(?:feeds|serves|makes|yields|is\s+(?:enough\s+)?for)\s+"
                                r"(?:about\s+|around\s+|roughly\s+|up\s+to\s+)?(\d+(?:\.\d+)?)(?![\w.])",
                                re.IGNORECASE)
# Words that make the second number something other than a new total:
# "3 dozen", "2 batches", "4 more people".
_NOT_A_TOTAL_RE = re.compile(r"\b(dozen|batch(?:es)?|more|extra|additional|another)\b", re.IGNORECASE)


def detect_stated_yield(question):
    """How much the recipe makes and how much she wants, when she says
    both ("it usually feeds 5, make it feed 8" -> (5.0, 8.0)), read
    without the model: the model tends to take the recipe's yield line
    over her number. None unless the request has exactly two counts and
    says which one is the recipe's; anything else goes to the model."""
    originals = [float(m.group(1)) for m in _ORIGINAL_YIELD_RE.finditer(question or "")]
    counts = count_numbers(question)
    if len(originals) != 1 or len(counts) != 2 or originals[0] not in counts or _NOT_A_TOTAL_RE.search(question):
        return None
    counts.remove(originals[0])
    return originals[0], counts[0]


def stated_yield_factor(question):
    """(factor, explanation) for a request detect_stated_yield reads,
    else None."""
    stated = detect_stated_yield(question)
    if stated is None:
        return None
    original, target = stated
    return _check_sane(target / original, f"Yield scaling (as you stated it): {target:g} ÷ {original:g} "
                                          f"= {target / original:.3f}x")


# Her amount and its unit: "50 g", "2 cups", "1" (in "1 egg").
_STATED_AMOUNT_RE = re.compile(r"(?<![\w./])(\d+/\d+|\d+(?:\.\d+)?)\s*(g|grams?|kg|kilograms?|ml|milliliters?|l|"
                               r"liters?|cups?|oz|ounces?|pounds?|lbs?|tablespoons?|teaspoons?|tbsp|tsp)?\b",
                               re.IGNORECASE)
_GRAMS = {"g": 1, "gram": 1, "kg": 1000, "kilogram": 1000, "oz": 28.35, "ounce": 28.35,
          "lb": 453.6, "pound": 453.6}
_ML = {"ml": 1, "milliliter": 1, "l": 1000, "liter": 1000}
_ML_PER_TSP = 4.929


def _singular(unit):
    unit = (unit or "").lower().rstrip(".")
    return unit[:-1] if unit.endswith("s") and unit[:-1] in _GRAMS | _ML else unit


def stated_unit(question, amount):
    """The unit she gave her amount in ("I only have 50 g of butter" ->
    "g"), or None for a count ("I only have 1 egg") or an amount not
    written as a number."""
    for m in _STATED_AMOUNT_RE.finditer(question or ""):
        num = m.group(1)
        value = float(num.split("/")[0]) / float(num.split("/")[1]) if "/" in num else float(num)
        if abs(value - amount) < 1e-9:
            return _singular(m.group(2)) or None
    return None


def comparable_amounts(ing, amount, unit):
    """(her amount, the recipe's amount, the recipe's amount as printed)
    with the first two in the same unit, or None when the line has
    nothing to compare her unit with. A count ("1 egg") goes against the
    line's count ("2 large eggs" in "100 g / 2 large eggs"), grams
    against grams, cups against cups."""
    metric, metric_unit = ing["metric_amount"], _singular(ing["metric_unit"])
    imperial, imperial_unit = ing["imperial_amount"], _singular(ing["imperial_unit"])
    imperial_tsp = to_teaspoons(imperial, imperial_unit) if imperial else None
    as_metric = f"{metric:g} {ing['metric_unit'] or ''}".strip() if metric else None
    as_imperial = f"{imperial:g} {ing['imperial_unit'] or ''}".strip() if imperial else None
    if unit is None:
        if imperial and imperial_tsp is None and imperial_unit not in _GRAMS:
            return amount, imperial, as_imperial      # a count, or "1 stick", "1 can"
        if metric:                                     # she left the unit off
            return amount, metric, as_metric
        return (amount, imperial, as_imperial) if imperial else None
    if unit in _GRAMS:
        if metric and metric_unit in _GRAMS:
            return amount * _GRAMS[unit], metric * _GRAMS[metric_unit], as_metric
        if imperial and imperial_unit in _GRAMS:
            return amount * _GRAMS[unit], imperial * _GRAMS[imperial_unit], as_imperial
        return None
    tsp = to_teaspoons(amount, unit)
    ml = amount * _ML[unit] if unit in _ML else float(tsp) * _ML_PER_TSP
    if metric and metric_unit in _ML:
        return ml, metric * _ML[metric_unit], as_metric
    if imperial_tsp is not None:
        return ml / _ML_PER_TSP, float(imperial_tsp), as_imperial
    return None


def _measured_as(ing):
    return " / ".join(f"{amount:g} {unit or ''}".strip() for amount, unit in
                      ((ing["metric_amount"], ing["metric_unit"]), (ing["imperial_amount"], ing["imperial_unit"]))
                      if amount)


def _quoted(yield_line, longest=40):
    """ (\"Serves 8\") to put after "makes", or nothing when the yield
    line is missing or too long to read as one (it can run on into the
    ingredients)."""
    line = " ".join((yield_line or "").split())
    return f' ("{line}")' if line and len(line) <= longest else ""


def resolve_scale_factor(intent, ingredients, yield_line="", question=""):
    """Deterministically turn the model's reported intent into an actual
    scale factor. Returns (factor, explanation) on success,
    (None, reason) if it can't be resolved, or
    ("ambiguous", [candidate_names]) if an ingredient reference matched
    more than one parsed ingredient and needs disambiguation.

    With the yield line and the request, a yield the model read from a
    weight or volume ("141 g") that the request didn't state itself is
    refused: scaling grams of whipped cream to "12 people" is a guess.
    """
    basis = normalize_basis(intent)

    if basis == "conflicting":
        return None, f"I couldn't tell how you want to scale this. {TRY_INSTEAD}"

    if basis == "direct":
        factor = intent.get("direct_multiplier")
        if not factor:
            return None, f"I couldn't tell how much to scale it by. {TRY_INSTEAD}"
        return _check_sane(factor, f"Direct multiplier: {factor}x")

    if basis == "yield":
        target = intent.get("target_yield")
        original = intent.get("original_yield")
        stated = {float(n) for n in _NUMBER_RE.findall(question or "")}
        # She gave both numbers ("it feeds 5, make it feed 8") but the
        # model took the original from the yield line ("SERVES 8", so
        # 8 -> 8): use hers.
        counts = count_numbers(question)
        if target and original and len(counts) == 2 and target in counts and \
                (original not in counts or (original == target and counts[0] != counts[1])):
            counts.remove(target)
            original = counts[0]
        in_line = {float(n) for n in _NUMBER_RE.findall(yield_line or "")}
        if re.search(r"\bdozen\b", yield_line or "", re.IGNORECASE):
            in_line |= {12 * n for n in in_line} | {12.0}
        # A yield neither the recipe nor she stated was made up.
        if original and yield_line and original not in in_line | stated:
            return None, (f"I couldn't tell how many this recipe makes{_quoted(yield_line)}. Tell me how many it "
                          f'feeds ("it feeds 6, make it for 10"), or try "double it".')
        if target and (not original or (original in yield_measure_numbers(yield_line) and original not in stated)):
            return None, (f"This recipe says how much it makes as an amount{_quoted(yield_line)}, not as servings "
                          f"or pieces, so I can't scale it to {target:g}. Tell me how many it feeds (\"it feeds 6, "
                          f"make it for 10\"), or try \"double it\" or how much of one ingredient you have.")
        if not target or not original:
            return None, ('I couldn\'t tell how many the recipe makes or how many you want. Try "it feeds 6, '
                          'make it for 10".')
        factor = target / original
        return _check_sane(factor, f"Yield scaling: {target:g} \u00f7 {original:g} = {factor:.3f}x")

    if basis == "ingredient_constraint":
        ref = (intent.get("reference_ingredient") or "").strip().lower()
        target_amt = intent.get("target_ingredient_amount")
        if not ref or not target_amt:
            return None, ('I couldn\'t tell which ingredient you mean or how much of it you have. Try '
                          '"I only have 2 eggs".')

        # An ingredient with no amount ("Egg wash", "Butter for the pan")
        # can't set a scale factor, and leaving it out keeps "I only have
        # 1 egg" from also matching "Egg wash".
        matches = [ing for ing in ingredients
                   if ref in ing["name"].lower() and not ing.get("unmeasured")]
        if not matches:
            return None, f'This recipe doesn\'t seem to use "{ref}", so I can\'t scale it by that.'
        if len(matches) > 1:
            return "ambiguous", [m["name"] for m in matches]

        matched = matches[0]
        if not (matched["metric_amount"] or matched["imperial_amount"]):
            return None, f'I couldn\'t read how much {matched["name"]} the recipe calls for, so I can\'t scale by it.'
        unit = stated_unit(question, target_amt)
        amounts = comparable_amounts(matched, target_amt, unit)
        if amounts is None:
            return None, (f'The recipe measures {matched["name"]} as {_measured_as(matched)}, which I can\'t '
                          f'compare with {target_amt:g} {unit}. Try giving it in one of those units.')
        have, original_amt, printed = amounts
        factor = have / original_amt
        yours = f"{target_amt:g} {unit}" if unit else f"{target_amt:g}"
        return _check_sane(factor, f'Ingredient scaling: {matched["name"]} {yours} \u00f7 {printed} = {factor:.3f}x')

    return None, f"I couldn't tell how you want to scale this. {TRY_INSTEAD}"


def _round_to_increment(value, increment):
    """Round to the nearest multiple of increment, e.g. increment=1 for
    whole numbers, increment=0.25 for quarters. Returns (rounded, was_rounded)."""
    rounded = round(value / increment) * increment
    # Avoid flagging a "rounding" that's really just float noise
    # (e.g. 12.000000001 vs 12).
    was_rounded = abs(rounded - value) > 1e-9
    return rounded, was_rounded


def _round_metric(unit, value):
    """Grams round to the nearest whole gram, most kitchen scales aren't
    precise enough to matter below that. Other metric units (ml, kg, l)
    are left with finer rounding for now.
    """
    if (unit or "").lower() == "g":
        return _round_to_increment(value, 1)
    return _round_to_increment(value, 0.1)


def scale_ingredients(ingredients, factor):
    """Apply a scale factor to every ingredient. Pure arithmetic, no model
    involved. Also attaches any exception-list flags per ingredient.

    scaled_metric is rounded here (nearest whole gram). scaled_imperial
    is left as the raw, un-rounded value on purpose, volume units
    (teaspoon/tablespoon/cup) need the full decomposition logic in
    measurement_display.py to pick a sensible combination of real
    measuring tools, not a single rounded number, that decision needs
    the un-rounded value to work from.
    """
    scaled = []
    for ing in ingredients:
        scaled_metric = scaled_metric_rounded = None
        if ing["metric_amount"]:
            raw = ing["metric_amount"] * factor
            scaled_metric, scaled_metric_rounded = _round_metric(ing["metric_unit"], raw)

        scaled_imperial = ing["imperial_amount"] * factor if ing["imperial_amount"] else None
        flags = check_ingredient_flags(ing["name"])
        scaled_imperial, rounded_whole = _whole(ing, scaled_imperial, factor, flags)

        scaled.append({
            "name": ing["name"],
            "original_metric": ing["metric_amount"],
            "original_imperial": ing["imperial_amount"],
            "original_imperial_display": ing.get("imperial_display"),
            "metric_unit": ing["metric_unit"],
            "imperial_unit": ing["imperial_unit"],
            "scaled_metric": scaled_metric,
            "scaled_metric_rounded": scaled_metric_rounded,
            "scaled_imperial": scaled_imperial,
            "scaled_imperial_rounded": rounded_whole,
            "qualifier": ing.get("qualifier"),
            "unmeasured": ing.get("unmeasured", False),
            "flags": flags,
        })
    return scaled


def _whole(ing, scaled_imperial, factor, flags):
    """A scaled count of something that only comes whole: a crust stays
    as the recipe has it, a can or a pinch is rounded to a whole number
    (at least 1). Adds a note to flags when that changes much. Returns
    (scaled_imperial, was_rounded)."""
    kind = whole_item(ing) if scaled_imperial and factor != 1 else None
    if kind is None:
        return scaled_imperial, False
    what, note = kind
    if what == "not_scaled":
        flags.append(("non_scalable", note))
        return ing["imperial_amount"], False
    whole = max(1, math.floor(scaled_imperial + 0.5))
    if what == "whole" and abs(whole - scaled_imperial) > 0.1 * scaled_imperial:
        exact = f"{scaled_imperial:.2f}".rstrip("0").rstrip(".")
        flags.append(("rounded", f"Rounded up to {whole}; the exact amount is {exact}, so use part of the last one "
                                 f"if it matters." if whole > scaled_imperial else
                                 f"Rounded down to {whole}; the exact amount is {exact}."))
    return whole, abs(whole - scaled_imperial) > 1e-9
