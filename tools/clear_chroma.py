"""
Delete the entire Chroma database, so the next ingest starts clean.

Run from app/ (either form works):
    python3 tools/clear_chroma.py
    python3 -m tools.clear_chroma

Rarely needed: ingest.py replaces a book's chunks on every run, so
re-ingesting a book never leaves old ones behind. Use this to drop a
book that's no longer ingested, or to start over. Every book has to be
re-ingested afterward, and the saved extractions (EXTRACT_DIR) are kept,
so that's only the embedding time.
"""

import os
import shutil
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared config below can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config import CHROMA_PATH, RECIPE_INDEX_PATH  # noqa: E402  (needs the path above)


if __name__ == "__main__":
    path = os.path.abspath(CHROMA_PATH)
    index_path = os.path.abspath(RECIPE_INDEX_PATH)
    if not os.path.exists(path):
        print(f"Nothing to clear, {path} doesn't exist.")
    else:
        # The recipe index is built from the database, so it goes too.
        also = f" and {index_path}" if os.path.exists(index_path) else ""
        answer = input(f"Delete {path} and everything in it{also}? [y/N] ")
        if answer.strip().lower() == "y":
            shutil.rmtree(path)
            if also:
                os.remove(index_path)
            print("Cleared.")
        else:
            print("Cancelled, nothing deleted.")
