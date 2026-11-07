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

import re

from common import models
from common.word_list_loader import load_universal
from scale_utils.scaling_rules import check_ingredient_flags

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
    q = question.lower()
    words = load_universal("direct_multipliers.json", {"words": _DEFAULT_MULTIPLIERS}).get("words", _DEFAULT_MULTIPLIERS)

    for word, factor in words.items():
        if re.search(rf"\b{word}\b", q):
            return factor

    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:x|times)\b", q)
    if m:
        return float(m.group(1))

    m = re.search(r"\bscale(?:d)?\s+by\s+(\d+(?:\.\d+)?)\b", q)
    if m:
        return float(m.group(1))

    return None


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


def _check_sane(factor, explanation):
    """Reject an internally-plausible-looking but almost certainly wrong
    factor before it ever reaches the multiplication step. A model
    misreading a yield line's own two numbers as "before" and "after"
    (as happened in testing) produces a factor that passed every earlier
    check yet was still nonsense, this catches that class of failure.
    """
    if factor < MIN_SANE_FACTOR or factor > MAX_SANE_FACTOR:
        return None, f"{explanation} — this factor is outside a sane range, likely a misread, not applying it"
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
        return None, ("The model's response mixed signals from more than one "
                       "scaling type at once, which usually means it misread "
                       "something. Try rephrasing more simply, e.g. \"double it\".")

    if basis == "direct":
        factor = intent.get("direct_multiplier")
        if not factor:
            return None, "No multiplier was given"
        return _check_sane(factor, f"Direct multiplier: {factor}x")

    if basis == "yield":
        target = intent.get("target_yield")
        original = intent.get("original_yield")
        stated = {float(n) for n in _NUMBER_RE.findall(question or "")}
        in_line = {float(n) for n in _NUMBER_RE.findall(yield_line or "")}
        if re.search(r"\bdozen\b", yield_line or "", re.IGNORECASE):
            in_line |= {12 * n for n in in_line} | {12.0}
        # A yield neither the recipe nor she stated was made up.
        if original and yield_line and original not in in_line | stated:
            return None, (f"I couldn't find how much the recipe makes (read it as {original:g}, which isn't in "
                          f'"{yield_line.strip()}"). Try a multiplier ("double it") or how much of one ingredient '
                          f"you have")
        if target and (not original or (original in yield_measure_numbers(yield_line) and original not in stated)):
            return None, ("the recipe's yield isn't a number of servings or pieces, so I can't scale it to "
                          f"{target:g}. Try a multiplier (\"double it\") or how much of one ingredient you have")
        if not target or not original:
            return None, "Missing target or original yield"
        factor = target / original
        return _check_sane(factor, f"Yield scaling: {target} \u00f7 {original} = {factor:.3f}x")

    if basis == "ingredient_constraint":
        ref = (intent.get("reference_ingredient") or "").strip().lower()
        target_amt = intent.get("target_ingredient_amount")
        if not ref or not target_amt:
            return None, "Missing reference ingredient or target amount"

        # An ingredient with no amount ("Egg wash", "Butter for the pan")
        # can't set a scale factor, and leaving it out keeps "I only have
        # 1 egg" from also matching "Egg wash".
        matches = [ing for ing in ingredients
                   if ref in ing["name"].lower() and not ing.get("unmeasured")]
        if not matches:
            return None, f'Could not find "{ref}" in this recipe\'s ingredients'
        if len(matches) > 1:
            return "ambiguous", [m["name"] for m in matches]

        matched = matches[0]
        original_amt = matched["metric_amount"] or matched["imperial_amount"]
        if not original_amt:
            return None, f'Found "{matched["name"]}" but couldn\'t read its amount'
        factor = target_amt / original_amt
        return _check_sane(factor, (
            f'Ingredient scaling: {matched["name"]} '
            f'{target_amt} \u00f7 {original_amt} = {factor:.3f}x'
        ))

    return None, f"Unrecognized basis: {basis!r}"


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
            "qualifier": ing.get("qualifier"),
            "unmeasured": ing.get("unmeasured", False),
            "flags": check_ingredient_flags(ing["name"]),
        })
    return scaled
