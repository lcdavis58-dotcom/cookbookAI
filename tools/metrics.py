"""
Reliability numbers from the saved chats (every account's) and the
flags, per app version (chat/metrics.py): how replies were routed, the
model's tool calls that couldn't run as called, reply and model times,
the answer checks, and flags.

Each run rewrites metrics.md in the data folder, so it can be read
without running this again. It quotes no book text.

Run from app/:
    python3 tools/metrics.py
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chat import metrics  # noqa: E402
from common.config import CHATS_DIR, DATA_DIR, FLAGS_DIR  # noqa: E402

METRICS_PATH = os.path.join(DATA_DIR, "metrics.md")


def main(argv=None, chats_dir=CHATS_DIR, flags_dir=FLAGS_DIR, path=METRICS_PATH):
    argparse.ArgumentParser(description="Reliability numbers from the saved chats and flags.").parse_args(argv)
    lines = metrics.write(path, chats_dir, flags_dir)
    print("\n".join(lines))
    print(f"Saved to {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
