"""
How long the chat model takes, per model and job (route, answer, scale
intent), from the timings saved with every chat reply (see
common/models.py). For deciding whether a bigger model is worth the
wait: run a few chats on each, then compare.

Run from app/ (either form works):
    python3 tools/diagnostics/model_timing.py
    python3 tools/diagnostics/model_timing.py --chats path/to/chats
"""

import argparse
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from chat import store  # noqa: E402
from common.config import CHATS_DIR  # noqa: E402


def collect(directory):
    """{(model, job): [seconds, ...]} over every readable chat, plus
    {model: [seconds of model time per reply that used the model]}."""
    calls, per_reply = defaultdict(list), defaultdict(list)
    for summary in store.list_chats(directory):
        if summary.error:
            continue
        for turn in store.load(summary.id, directory).messages:
            by_model = defaultdict(float)
            for call in turn.model_calls or []:
                calls[(call["model"], call["job"])].append(call["seconds"])
                by_model[call["model"]] += call["seconds"]
            for model, seconds in by_model.items():
                per_reply[model].append(seconds)
    return calls, per_reply


def row(label, times):
    times = sorted(times)
    return (f"  {label:<28} {len(times):>5}  {statistics.median(times):>7.1f}s"
            f"  {times[int(0.9 * (len(times) - 1))]:>7.1f}s  {times[-1]:>7.1f}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--chats", default=CHATS_DIR, help="the folder of saved chats")
    args = parser.parse_args()
    calls, per_reply = collect(args.chats)
    if not calls:
        print(f"No model calls saved in {os.path.abspath(args.chats)} yet.")
        return
    header = f"  {'':<28} {'calls':>5}  {'median':>8}  {'90%':>8}  {'slowest':>8}"
    for model in sorted({m for m, _ in calls}):
        print(f"\n{model}\n{header}")
        for (m, job), times in sorted(calls.items()):
            if m == model:
                print(row(job, times))
        print(row("whole reply (model time)", per_reply[model]))


if __name__ == "__main__":
    main()
