"""
Rebuild the recipe index (match_utils/recipe_index.py) from what's
already in the database, without re-ingesting. ingest.py does this on
its own at the end; run this after changing ingredient parsing or
normalization, which only changes the index, not the stored chunks.

Run from app/ (either form works):
    python3 tools/build_recipe_index.py
    python3 -m tools.build_recipe_index
"""

import os
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config import RECIPE_INDEX_PATH  # noqa: E402
from match_utils.recipe_index import build_index, save_index, summarize  # noqa: E402

if __name__ == "__main__":
    entries = build_index()
    save_index(entries)
    print("\n".join(summarize(entries)))
    print(f"Saved to {os.path.abspath(RECIPE_INDEX_PATH)}")
