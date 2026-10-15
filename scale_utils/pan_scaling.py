"""
Pan-size scaling: determine a pan's shape and dimensions from text, then
scale by area ratio. Entirely deterministic, like detect_direct_multiplier,
this is a geometry problem once dimensions are extracted, there's no
judgment call for a model to make, so it never needs one.

IMPORTANT SCOPING NOTE: extract_pan_shape() should be run against a
SCOPED piece of text (the recipe's yield line via extract_yield_line(),
or the user's own question), never a whole recipe chunk. Recipe bodies
mention other measurements too (dough thickness, cut rectangle sizes)
that look identical to a pan dimension and would be wrongly picked up.
"""

import re
import math

from common.text_parsing import parse_amount, FRACTION_CHARS
from common.word_list_loader import load_universal

NUM = rf"\d+(?:[{FRACTION_CHARS}])?|[{FRACTION_CHARS}]"
INCH_TO_CM = 2.54


def normalize_connectors(text):
    """"-by-" and "×" both mean the same thing as " by "/"x", collapse
    them to one form before matching."""
    text = re.sub(r"-by-", " by ", text, flags=re.IGNORECASE)
    text = text.replace("\u00d7", "x")
    return text


DIM_PAIR_RE = re.compile(
    rf"({NUM})\s*(?:x|by)\s*({NUM})\s*(inch(?:es)?|in\.?|cm|centimeters?)?",
    re.IGNORECASE,
)
SINGLE_DIM_RE = re.compile(
    rf"({NUM})[\s-]*(inch(?:es)?|in\.?|cm|centimeters?)\b",
    re.IGNORECASE,
)


def _to_inches(value, unit):
    unit = (unit or "in").lower()
    if unit.startswith("cm") or unit.startswith("centi"):
        return value / INCH_TO_CM
    return value


def extract_all_pan_shapes(text):
    """Find every distinct pan shape mentioned in a piece of text, in the
    order they appear. Used when both the original and target pan sizes
    are stated together in one question ("the recipe calls for a 9x9 pan
    but I only have an 8x8"), rather than relying on the recipe's own
    yield line, which doesn't always state a pan size at all.
    """
    text = normalize_connectors(text)
    found = []
    consumed_spans = []

    for m in DIM_PAIR_RE.finditer(text):
        length = parse_amount(m.group(1))
        width = parse_amount(m.group(2))
        if length is None or width is None:
            continue
        length, width = _to_inches(length, m.group(3)), _to_inches(width, m.group(3))
        found.append((m.start(), {"shape": "rectangle", "length": length, "width": width}))
        consumed_spans.append((m.start(), m.end()))

    for m in SINGLE_DIM_RE.finditer(text):
        # Skip if this is just one half of a pair already captured above
        # (e.g. "16 inches" inside an already-matched "8 by 16 inches").
        if any(s <= m.start() < e for s, e in consumed_spans):
            continue
        diameter = parse_amount(m.group(1))
        if diameter is None:
            continue
        diameter = _to_inches(diameter, m.group(2))
        nearby = text[max(0, m.start() - 20):m.end() + 20].lower()
        if "square" in nearby:
            found.append((m.start(), {"shape": "rectangle", "length": diameter, "width": diameter}))
        else:
            found.append((m.start(), {"shape": "circle", "diameter": diameter}))

    found.sort(key=lambda f: f[0])
    return [pan for _, pan in found]


def extract_pan_shape(text):
    """Find a pan shape + dimensions in a scoped piece of text. Returns
    {"shape": "rectangle", "length": L, "width": W} or
    {"shape": "circle", "diameter": D}, both in inches, or None if
    nothing resolvable was found. When both an inches and a cm version of
    the same dimension are present (this book's convention), inches is
    preferred and cm is used only as a fallback/conversion source.
    """
    text = normalize_connectors(text)

    pair_matches = list(DIM_PAIR_RE.finditer(text))
    if pair_matches:
        best = next((m for m in pair_matches if (m.group(3) or "").lower().startswith("in") or not m.group(3)), pair_matches[0])
        length = parse_amount(best.group(1))
        width = parse_amount(best.group(2))
        unit = best.group(3)
        if length is None or width is None:
            return None
        length, width = _to_inches(length, unit), _to_inches(width, unit)
        return {"shape": "rectangle", "length": length, "width": width}

    single_matches = list(SINGLE_DIM_RE.finditer(text))
    if single_matches:
        best = next((m for m in single_matches if (m.group(2) or "").lower().startswith("in")), single_matches[0])
        diameter = parse_amount(best.group(1))
        if diameter is None:
            return None
        diameter = _to_inches(diameter, best.group(2))

        nearby = text[max(0, best.start() - 20):best.end() + 20].lower()
        if "square" in nearby:
            return {"shape": "rectangle", "length": diameter, "width": diameter}
        return {"shape": "circle", "diameter": diameter}

    return None


def pan_area(pan):
    if pan["shape"] == "rectangle":
        return pan["length"] * pan["width"]
    if pan["shape"] == "circle":
        return math.pi * (pan["diameter"] / 2) ** 2
    return None


def describe_pan(pan):
    if pan["shape"] == "rectangle":
        return f'{pan["length"]:.2g}x{pan["width"]:.2g}in rectangle'
    return f'{pan["diameter"]:.2g}in circle'


def pan_scale_factor(original_text, target_text):
    """Returns (factor, explanation) on success, (None, reason) if either
    side's pan size couldn't be found."""
    original = extract_pan_shape(original_text)
    target = extract_pan_shape(target_text)

    if original is None:
        return None, "Couldn't find a pan size in the recipe's own yield line"
    if target is None:
        return None, "Couldn't find a pan size in your request"

    orig_area = pan_area(original)
    target_area = pan_area(target)
    factor = target_area / orig_area

    return factor, (
        f"Pan scaling: {describe_pan(target)} ({target_area:.1f} sq in) "
        f"\u00f7 {describe_pan(original)} ({orig_area:.1f} sq in) = {factor:.3f}x"
    )


_DEFAULT_ORIGINAL_CUES = ["recipe calls for", "recipe wants", "recipe uses", "recipe requires",
                           "recipe needs", "normally uses", "calls for", "the recipe"]
_DEFAULT_TARGET_CUES = ["i only have", "i've got", "i have", "i got", "mine is",
                         "only have", "but i have", "but mine"]


def _load_pan_cues():
    defaults = {"original_cues": _DEFAULT_ORIGINAL_CUES, "target_cues": _DEFAULT_TARGET_CUES}
    return load_universal("pan_cues.json", defaults)


def _nearest_cue_role(text, position, window=40):
    """Look at the text immediately before a matched pan mention for a
    role-indicating phrase. Returns "original", "target", or None if
    neither cue is present nearby.
    """
    cues = _load_pan_cues()
    preceding = text[max(0, position - window):position].lower()
    original_hit = max((preceding.rfind(c) for c in cues["original_cues"] if c in preceding), default=-1)
    target_hit = max((preceding.rfind(c) for c in cues["target_cues"] if c in preceding), default=-1)

    if original_hit == -1 and target_hit == -1:
        return None
    return "target" if target_hit > original_hit else "original"


_DEFAULT_PAN_KEYWORDS = ["pan", "dish", "tin"]


def detect_pan_request(question):
    """Cheap keyword gate: does this question look like it's about pan
    size at all? Used to decide whether to attempt pan-size extraction
    (and surface a pan-specific error if that fails) versus silently
    moving on to try a different scaling interpretation instead.
    """
    q = question.lower()
    keywords = load_universal("pan_keywords.json", {"keywords": _DEFAULT_PAN_KEYWORDS}).get("keywords", _DEFAULT_PAN_KEYWORDS)
    return any(re.search(rf"\b{word}\b", q) for word in keywords)


def pan_scale_factor_from_question(question):
    """Both the recipe's original pan and the user's target pan are
    expected to be stated together in the question itself.

    Role assignment prefers CUE PHRASES ("recipe calls for" vs. "I only
    have") when present, since order alone gets this wrong for reversed
    phrasing ("I have an 8x8, but the recipe wants a 9x9", target
    mentioned first there). Falls back to assuming the first pan
    mentioned is the original when no cues are found, since that matches
    every other phrasing pattern seen in this project so far.

    Returns (factor, explanation) on success, (None, reason) otherwise.
    """
    normalized = normalize_connectors(question)
    pans = extract_all_pan_shapes(question)

    if len(pans) < 2:
        return None, (f"Found {len(pans)} pan size(s) in your question, need two "
                       f"(the recipe's pan and the one you have) to scale by pan size.")
    if len(pans) > 2:
        return None, (f"Found {len(pans)} pan sizes in your question, not sure which "
                       f"two to compare. Try mentioning just the recipe's pan and yours.")

    # Re-find positions to check cues (extract_all_pan_shapes doesn't
    # expose them), matching the same logic it uses internally.
    positions = [m.start() for m in DIM_PAIR_RE.finditer(normalized)]
    consumed = [(m.start(), m.end()) for m in DIM_PAIR_RE.finditer(normalized)]
    for m in SINGLE_DIM_RE.finditer(normalized):
        if not any(s <= m.start() < e for s, e in consumed):
            positions.append(m.start())
    positions.sort()

    roles = [_nearest_cue_role(normalized, pos) for pos in positions[:2]]

    if roles[0] == "target" and roles[1] == "original":
        original, target = pans[1], pans[0]
    elif roles[0] == "original" and roles[1] == "target":
        original, target = pans[0], pans[1]
    else:
        # No clear cues (or same cue twice), fall back to order.
        original, target = pans[0], pans[1]

    orig_area = pan_area(original)
    target_area = pan_area(target)
    factor = target_area / orig_area

    return factor, (
        f"Pan scaling: {describe_pan(target)} ({target_area:.1f} sq in) "
        f"\u00f7 {describe_pan(original)} ({orig_area:.1f} sq in) = {factor:.3f}x"
    )


if __name__ == "__main__":
    # Examples in the book's style, testing the scoping risk directly:
    # the dough-thickness fraction sitting right next to the real pan
    # size should NOT get picked up as the dimension.
    tests = [
        "10 by 14 inches / 25 by 36 cm and just over \u00bc inch / 6 mm thick.",
        "three 5-by-12-inch / 13-by-30-cm strips",
        "roll the dough into a square about 14 by 14 inches",
        "MAKES ONE 9-INCH / 23-CM TART | DIFFICULTY: EASY",
        "a 9-inch square pan",
        "I only have an 8x8 pan",
    ]
    for t in tests:
        result = extract_pan_shape(t)
        print(f"{t!r}\n  -> {result}\n")
