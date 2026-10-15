"""
Turns a scaled volume amount (in teaspoons, tablespoons, or cups) into a
combination of pieces that map to real, ownable measuring tools, instead
of a single large or awkward number ("50 teaspoons", "0.9 cups").

All internal math uses exact Fraction arithmetic in teaspoons, since
teaspoon/tablespoon/cup have exact whole-number relationships to each
other (3 tsp = 1 tbsp, 48 tsp = 1 cup). Working in milliliters instead
would introduce rounding error that doesn't need to exist.

The only place any real rounding happens is snapping the true scaled
amount to the nearest quarter-teaspoon, our finest practically-usable
resolution. Everything after that (splitting into cup/tbsp/tsp pieces)
is an exact decomposition of that snapped value, no further precision is
lost by choosing, say, one cup-fraction over two.
"""

from fractions import Fraction

TSP_PER_TBSP = 3
TSP_PER_CUP = 48

# Standard measuring cup sizes, largest first. Deliberately does NOT
# include 1.5 cup, not a standard tool, composite amounts like 1.5 cups
# fall out naturally as "1 whole cup" + "1/2 cup" fractional piece.
CUP_FRACTIONS = [Fraction(3, 4), Fraction(2, 3), Fraction(1, 2),
                  Fraction(1, 3), Fraction(1, 4), Fraction(1, 8)]
CUP_FRACTION_TSP = [f * TSP_PER_CUP for f in CUP_FRACTIONS]  # [36, 32, 24, 16, 12, 6]


def to_teaspoons(amount, unit):
    """Convert an amount+unit to an exact Fraction of teaspoons. Returns
    None if this isn't a volume unit we handle (e.g. ounces, or a bare
    count), the caller should fall back to generic rounding for those.
    """
    unit = (unit or "").lower()
    amt = Fraction(amount).limit_denominator(1000)
    if "teaspoon" in unit or unit == "tsp":
        return amt
    if "tablespoon" in unit or unit == "tbsp":
        return amt * TSP_PER_TBSP
    if "cup" in unit:
        return amt * TSP_PER_CUP
    return None


def snap_to_quarter_tsp(tsp_amount):
    """Round to the nearest quarter-teaspoon, our finest measurable
    resolution. Returns (snapped_fraction, was_rounded)."""
    quarters = round(tsp_amount * 4)
    snapped = Fraction(quarters, 4)
    return snapped, snapped != tsp_amount


def _format_fraction(frac):
    """Render a Fraction as "2", "3/4", or "1 1/4", never a decimal."""
    whole = frac.numerator // frac.denominator
    remainder = frac - whole
    if remainder == 0:
        return str(whole)
    frac_str = f"{remainder.numerator}/{remainder.denominator}"
    return f"{whole} {frac_str}" if whole else frac_str


def _unit_word(qty, singular):
    return singular if qty <= 1 else singular + "s"


def decompose_cup_remainder(remainder_tsp):
    """remainder_tsp is < TSP_PER_CUP (a sub-1-cup amount). Tries, in
    order: an exact single cup-fraction match, then an exact PAIR of cup
    fractions summing to the target (this catches cases a pure
    largest-first-greedy would miss, e.g. 1/3 + 1/4 exactly meeting a
    target that a greedy pick of 1/2 first would overshoot past). Only
    if neither exists does it fall back to the single best-fitting
    fraction plus a genuine leftover.

    Returns (list of (Fraction, "cup") pieces, leftover_tsp).
    """
    if remainder_tsp == 0:
        return [], Fraction(0)

    for frac, tsp_val in zip(CUP_FRACTIONS, CUP_FRACTION_TSP):
        if tsp_val == remainder_tsp:
            return [(frac, "cup")], Fraction(0)

    for i, (f1, t1) in enumerate(zip(CUP_FRACTIONS, CUP_FRACTION_TSP)):
        for f2, t2 in zip(CUP_FRACTIONS[i + 1:], CUP_FRACTION_TSP[i + 1:]):
            if t1 + t2 == remainder_tsp:
                ordered = [(f1, "cup"), (f2, "cup")] if f1 > f2 else [(f2, "cup"), (f1, "cup")]
                return ordered, Fraction(0)

    for frac, tsp_val in zip(CUP_FRACTIONS, CUP_FRACTION_TSP):
        if tsp_val <= remainder_tsp:
            return [(frac, "cup")], remainder_tsp - tsp_val

    return [], remainder_tsp  # smaller than our smallest fraction (1/8 cup)


def decompose_tbsp_tsp(tsp_amount):
    """Split an amount (in teaspoons) into whole tablespoons plus a
    teaspoon remainder. No fractional tablespoons, standard sets don't
    include a half-tablespoon tool.
    """
    whole_tbsp = tsp_amount // TSP_PER_TBSP
    remainder = tsp_amount - whole_tbsp * TSP_PER_TBSP

    pieces = []
    if whole_tbsp > 0:
        pieces.append((Fraction(whole_tbsp), "tablespoon"))
    if remainder > 0:
        pieces.append((remainder, "teaspoon"))
    if not pieces:
        pieces.append((Fraction(0), "teaspoon"))
    return pieces


def decompose_volume(amount, unit):
    """Main entry point. Returns (pieces, was_rounded), or (None, False)
    if `unit` isn't a volume unit this module handles.

    Which decomposition applies depends on the ingredient's ORIGINAL
    unit, not just the scaled amount's size:
      - Originally measured in cups: always prefer cup-fraction tools
        (rule 2), even for a sub-1-cup result, that's the whole reason
        this rule exists (0.9 cup shouldn't become "14 tablespoons" just
        because it's under a full cup).
      - Originally teaspoons/tablespoons: stay in tsp/tbsp terms (rule 1)
        unless the scaled amount has grown to a full cup or more, at
        which point cup terms are clearly friendlier regardless of where
        the ingredient started.
    """
    unit_lower = (unit or "").lower()
    total_tsp = to_teaspoons(amount, unit)
    if total_tsp is None:
        return None, False

    snapped, was_rounded = snap_to_quarter_tsp(total_tsp)

    if "cup" in unit_lower or snapped >= TSP_PER_CUP:
        whole_cups = snapped // TSP_PER_CUP
        remainder = snapped - whole_cups * TSP_PER_CUP

        pieces = []
        if whole_cups > 0:
            pieces.append((Fraction(whole_cups), "cup"))

        cup_pieces, leftover_tsp = decompose_cup_remainder(remainder)
        pieces.extend(cup_pieces)

        if leftover_tsp > 0:
            pieces.extend(decompose_tbsp_tsp(leftover_tsp))

        return pieces, was_rounded

    if snapped < TSP_PER_TBSP:
        return [(snapped, "teaspoon")], was_rounded

    return decompose_tbsp_tsp(snapped), was_rounded


def format_pieces(pieces):
    """Render a list of (Fraction, unit_name) pieces as a display string,
    e.g. "3/4 cup + 1/8 cup" or "2 tablespoons + 1 1/4 teaspoons"."""
    parts = [f"{_format_fraction(qty)} {_unit_word(qty, unit)}" for qty, unit in pieces]
    return " + ".join(parts)


# Non-volume units that need a plural form when displayed. Volume units
# get theirs from _unit_word() inside the decomposition path above.
COUNT_UNIT_PLURALS = {"stick": "sticks"}


def count_unit_label(qty, unit):
    """Unit text to show after a non-volume amount. A bare count ("1
    large egg yolk", "3 garlic cloves") has no unit at all, label it
    "whole" so "1 -> 2" doesn't read as a missing unit."""
    if not unit:
        return "whole"
    if unit in COUNT_UNIT_PLURALS and qty != 1:
        return COUNT_UNIT_PLURALS[unit]
    return unit


def format_imperial_amount(amount, unit):
    """Top-level helper for display code: given a scaled imperial amount
    and its original unit, return (display_string, was_rounded). Volume
    units (teaspoon/tablespoon/cup) get the full decomposition above,
    anything else (ounces, bare counts) falls back to plain rounding.
    """
    pieces, was_rounded = decompose_volume(amount, unit)
    if pieces is not None:
        return format_pieces(pieces), was_rounded

    rounded = round(amount, 2)
    display = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return f"{display} {count_unit_label(rounded, unit)}", rounded != amount


if __name__ == "__main__":
    tests = [
        (7 / 8, "cup"),   # expect: 3/4 cup + 1/8 cup, exact
        (0.9, "cup"),     # expect: 3/4 cup + some tbsp/tsp, approximate
        (50, "teaspoon"),  # expect: 1 cup + 2 teaspoons
        (8, "teaspoon"),   # expect: 2 tablespoons + 2 teaspoons (>3 tsp -> tbsp)
        (1, "teaspoon"),   # expect: stays as 1 teaspoon (<3 tsp)
        (3.5, "cup"),      # expect: 3 cups + 1/2 cup, exact
        (1 / 3 + 1 / 4, "cup"),  # expect: 1/3 cup + 1/4 cup (the greedy-miss case)
        (7, "teaspoon"),   # a small spice amount, should stay tbsp/tsp,
                            # NOT become "1/8 cup + 1 teaspoon" just
                            # because 7 tsp technically exceeds 1/8 cup
    ]
    for amount, unit in tests:
        display, rounded = format_imperial_amount(amount, unit)
        flag = "~" if rounded else ""
        print(f"{amount} {unit} -> {flag}{display}")
