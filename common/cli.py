"""
Command-line handling shared by query.py and scale.py, including the one
debug switch both scripts (and the utilities they call) read.
"""

import argparse

# Set by -d on the command line. Read it as cli.DEBUG (not "from
# common.cli import DEBUG", which would copy the value at import time and
# never see it change).
DEBUG = False


def parse_cli(description):
    """Parse an optional -d/--debug flag plus the question itself, which
    doesn't need quoting since every remaining word is joined back
    together. Returns (question, debug)."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="print retrieval candidates and matching/parsing diagnostics")
    parser.add_argument("question", nargs="+", help="your question or request")
    args = parser.parse_args()
    return " ".join(args.question), args.debug
