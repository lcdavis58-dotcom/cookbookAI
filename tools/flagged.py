"""
Review the replies flagged as wrong (chat/flags.py), from the website's
flag button and the terminal's /flag.

Each run rewrites two files in FLAGS_DIR, so they can be read without
running this again: open_flags.md (still to fix) and handled_flags.md.
Every entry has the whole chat up to the flagged reply.

Run from app/:
    python3 tools/flagged.py                              # rewrite the summaries, print counts
    python3 tools/flagged.py handled ID "what covers it"  # e.g. "1.1.2" or a test's name
    python3 tools/flagged.py reopen ID                    # undo a mistaken "handled"
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chat import flags  # noqa: E402
from common.config import FLAGS_DIR  # noqa: E402


def main(argv=None, directory=FLAGS_DIR):
    parser = argparse.ArgumentParser(description="Review the replies flagged as wrong.")
    commands = parser.add_subparsers(dest="command")
    handled = commands.add_parser("handled", help="mark a flag handled")
    handled.add_argument("id")
    handled.add_argument("covered_by", help="what covers it: a version or a test")
    reopen = commands.add_parser("reopen", help="mark a handled flag open again")
    reopen.add_argument("id")
    args = parser.parse_args(argv)

    try:
        if args.command == "handled":
            f = flags.mark_handled(args.id, args.covered_by, directory)
            print(f"Marked {f.id} handled by {f.handled_by!r}.")
        elif args.command == "reopen":
            f = flags.reopen(args.id, directory)
            print(f"Reopened {f.id}.")
    except flags.FlagError as e:
        sys.exit(f"Couldn't: {e}.")

    open_, done, bad = flags.write_summaries(directory)
    print(f"{len(open_)} open, {len(done)} handled.")
    print(f"  {os.path.join(directory, flags.OPEN_FILE)}")
    print(f"  {os.path.join(directory, flags.HANDLED_FILE)}")
    for problem in bad:
        print(f"  Couldn't read {problem}")


if __name__ == "__main__":
    main()
