"""
The Book On Pie: settings for the shared engine (books/engine.py). See
books/__init__.py for the interface every book module provides.

Format, for reference (sizes in points, as extracted):

    SPICED APPLE HAND PIES          25, ALL-CAPS, can wrap
    MAKES TWELVE 4-INCH / 10-CM HAND PIES | DIFFICULTY:
    EASY                            the rating can wrap onto its own line
    <intro prose>
    57 g / 2 ounces / 4 tablespoons unsalted butter, at room temperature
    67 g / ⅓ cup granulated sugar
    1. Preheat the oven to 400°F...

21pt is used inside recipes ("Make Ahead and Storage", "PIE-DEAS",
"PIE PEP TALK"), so only 25pt and up are headings.
"""

import re

TITLE_MIN_SIZE = 25
YIELD_RE = re.compile(r"^MAKES\b")
# The MAKES line usually carries "| DIFFICULTY: EASY" itself, but a long
# yield wraps it onto the next line.
HEADER_FIELD_RE = re.compile(r"DIFFICULTY", re.IGNORECASE)
INGREDIENT_STYLE = "metric_slash"

# Batch-size subsections are short ALL-CAPS labels ending in "BATCH"
# (HALF BATCH, FULL BATCH, MILE-HIGH BATCH). Matching the pattern rather
# than an exact list catches variants we haven't seen yet, without also
# catching VARIATION or NOTE. Batches are alternative sizes of the same
# recipe, only one gets made; any other label (FILLING, OPTIONAL
# TOPPING) is a component that always is (see
# scale_utils/ingredients.group_kind).
BATCH_LABEL_RE = re.compile(r"^[A-Z][A-Z\- ]*\bBATCH$")

# Sidebars set inside a recipe, after its steps: ideas, troubleshooting,
# explanations and crust pairings. Nothing after one is an ingredient of
# the recipe.
ASIDE_RE = re.compile(r"^(?:PIE-DEAS?|PIE PEP TALK|THE WHYS OF PIES|RECOMMENDED [A-Z ]+)$")


def section_label(line):
    """HALF BATCH / FULL BATCH / MILE-HIGH BATCH start a new group."""
    return line.title() if BATCH_LABEL_RE.match(line) else None
