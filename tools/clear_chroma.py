"""
Delete the entire Chroma database, so the next ingest starts clean.

Run from app/ (either form works):
    python3 tools/clear_chroma.py
    python3 -m tools.clear_chroma

Needed because ingest.py upserts chunks by id ("<book>-c<N>"), so a
re-ingest that produces fewer chunks than the last one leaves the extra
old chunks behind. Wiping everything means every book has to be
re-ingested afterward, not just the one you were fixing.
"""

import os
import shutil
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared config below can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config import CHROMA_PATH  # noqa: E402  (needs the path above)


if __name__ == "__main__":
    path = os.path.abspath(CHROMA_PATH)
    if not os.path.exists(path):
        print(f"Nothing to clear, {path} doesn't exist.")
    else:
        answer = input(f"Delete {path} and everything in it? [y/N] ")
        if answer.strip().lower() == "y":
            shutil.rmtree(path)
            print("Cleared.")
        else:
            print("Cancelled, nothing deleted.")
