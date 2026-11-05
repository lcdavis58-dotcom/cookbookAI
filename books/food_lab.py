"""
The Food Lab (J. Kenji López-Alt): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    COOLER-COOKED LAMB RACK         25 bold, ALL CAPS, wraps
    WITH SALSA VERDE                21.3 bold, the "with ..." line
    Chimichurri Sauce               21.3 bold alone: a small recipe
    <headnote>                      15, sometimes
    SERVES 4                        11.3 bold, or "MAKES ..."
    6 large eggs                    11.3 bold, US amounts
    ¾ teaspoon kosher salt
    1.  Combine the eggs, ...       15, numbered steps

Long science essays sit between recipes under the same heading sizes;
with no yield line they stay "other" chunks. The PDF's fraction glyphs
come out as accented letters ("ò cup"); extraction repairs them
(ingest_utils/extract.py).
"""

import re

TITLE_MIN_SIZE = 21
TITLE_BOLD = True
YIELD_RE = re.compile(r"^(?:SERVES|MAKES)\b")
INGREDIENT_STYLE = "volume_paren_metric"
# The method of a short recipe isn't numbered ("Whisk together all of the
# ingredients..."); those lines are rejected and dropped. Ending the list
# at the change from 11.3 to 15pt type (as books/htcev.py does with fonts)
# was tried and lost the sub-recipes printed after the main method (a
# salad's croutons and dressing, pesto variations), so it isn't used.


# "For the Biscuit Dough", "For the Sauce": group labels in Title Case
# (sentences that start the same way are lowercase: "For the most part").
_FOR_THE_RE = re.compile(r"^For the ((?:[A-Z][\w’'\-]*)(?:\s+(?:[A-Z][\w’'\-]*|and|with|or|of))*)$")


def section_label(line):
    m = _FOR_THE_RE.match(line.strip())
    return m.group(1) if m else None
