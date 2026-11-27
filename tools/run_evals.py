"""
The scored eval set: chat messages with what should come of them (the
route, the recipes shown, the scale, the books an answer cites), run
against the real recipe index, database and model, and scored. Run it
after a change, or with another model (CHAT_MODEL=...), to compare.

The cases are in testing/evals/cases.json. The repository is public, so
they hold only messages, titles, counts and numbers, never book text.
Each one:
    id          a short name
    since       the version it was added in
    setup       messages sent first, in a fresh chat (optional)
    message     the message being scored
    expect      any of:
        route           the route label starts with this ("rule: ask filter")
        how             "rule", "pending" or "model"
        recipe          the recipe shown
        titles          every one of these is in the list shown
        not_titles      none of these is
        count           how many recipes the list has, shown or not
        factor          the scale factor
        reply           every one of these is in the reply
        not_reply       none of these is
        books           the books an answer cites are among these

Results go to evals/ in the data folder (COOKBOOK_DATA_DIR), one file per
run, named by version and model, so runs can be compared over time.

Run from app/:
    python3 tools/run_evals.py                  # every case
    python3 tools/run_evals.py --only filter    # cases whose id has "filter"
    python3 tools/run_evals.py --repeat 3       # each case 3 times (model answers vary)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config import CHAT_MODEL, DATA_DIR, PROJECT_ROOT  # noqa: E402

CASES_PATH = os.path.join(PROJECT_ROOT, "testing", "evals", "cases.json")
RESULTS_DIR = os.environ.get("EVALS_DIR", os.path.join(DATA_DIR, "evals"))
CHECKS = ("route", "how", "recipe", "titles", "not_titles", "count", "factor", "reply", "not_reply", "books")


def load_cases(path=CASES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["cases"]


def shown(result):
    """What a turn's result showed: (recipe title or None, every listed
    title, shown or not, the factor or None, the books an answer cites)."""
    recipe = getattr(result, "recipe", None)
    listed = []
    for c in list(getattr(result, "choices", None) or []) + list(getattr(result, "rest", None) or []):
        listed.append(c.title)
    for name in ("ready", "from_scratch", "missing_some"):
        for r in getattr(result, name, None) or []:
            listed.append(r["entry"]["title"])
    sources = getattr(result, "sources", None) or []
    books = sorted({h["book"] for h in sources if isinstance(h, dict) and "book" in h})
    title = getattr(recipe, "title", None) if getattr(result, "kind", "") in ("recipe", "scaled") else None
    return title, listed, getattr(result, "factor", None), books


def score(case, turn):
    """The checks that failed, as ["what: expected ..., got ..."]; empty
    when the case passed. turn is a chat.turn.TurnResult."""
    expect, failed = case.get("expect", {}), []
    label = turn.route.label if turn.route else ""
    how = turn.route.how if turn.route else ""
    recipe, listed, factor, books = shown(turn.result) if turn.result is not None else (None, [], None, [])
    if "route" in expect and not label.startswith(expect["route"]):
        failed.append(f"route: expected {expect['route']!r}, got {label!r}")
    if "how" in expect and how != expect["how"]:
        failed.append(f"how: expected {expect['how']!r}, got {how!r}")
    if "recipe" in expect and recipe != expect["recipe"]:
        failed.append(f"recipe: expected {expect['recipe']!r}, got {recipe!r}")
    missing = [t for t in expect.get("titles", []) if t not in listed]
    if missing:
        failed.append(f"titles: missing {missing}")
    extra = [t for t in expect.get("not_titles", []) if t in listed]
    if extra:
        failed.append(f"not_titles: listed {extra}")
    if "count" in expect and len(listed) != expect["count"]:
        failed.append(f"count: expected {expect['count']}, got {len(listed)}")
    if "factor" in expect and (factor is None or abs(factor - expect["factor"]) > 1e-3):
        failed.append(f"factor: expected {expect['factor']}, got {factor}")
    for text in expect.get("reply", []):
        if text not in turn.text:
            failed.append(f"reply: missing {text!r}")
    for text in expect.get("not_reply", []):
        if text in turn.text:
            failed.append(f"not_reply: has {text!r}")
    if "books" in expect and not set(books) <= set(expect["books"]):
        failed.append(f"books: cited {sorted(set(books) - set(expect['books']))}")
    return failed


def run_case(case, respond):
    """One case in a fresh chat: {"id", "failed", "route", "seconds",
    "model_seconds", "checks"}. checks: what actions/answer_checks.py
    found in each model answer, in order (a second list means it was
    asked again). respond(state, message) answers a message."""
    from chat.state import ChatState
    from common import models

    state = ChatState.new()
    for message in case.get("setup", []):
        respond(state, message)
    models.clear()
    t0 = time.time()
    try:
        turn = respond(state, case["message"])
        failed = score(case, turn)
        label = turn.route.label if turn.route else ""
    except Exception as error:  # noqa: BLE001 - a crash is a failed case, not a stopped run
        failed, label = [f"error: {type(error).__name__}: {error}"], ""
    return {"id": case["id"], "failed": failed, "route": label, "seconds": round(time.time() - t0, 2),
            "model_seconds": round(sum(c["seconds"] for c in models.CALLS), 2),
            "checks": [c["checks"] for c in models.CALLS if "checks" in c]}


def summarize(results):
    passed = sum(1 for r in results if not r["failed"])
    by_model = [r for r in results if r["route"].startswith("model")]
    lines = [f"{passed}/{len(results)} passed ({100 * passed / max(1, len(results)):.0f}%)",
             f"{len(by_model)} routed by the model, {len(results) - len(by_model)} by rules or a pending question",
             f"model time: {sum(r['model_seconds'] for r in results):.1f}s in all"]
    checked = [r.get("checks") for r in results if r.get("checks")]
    if checked:
        again = sum(1 for c in checked if len(c) > 1)
        wrong = sum(1 for c in checked if c[-1])
        lines.append(f"{len(checked)} model answers checked: {len(checked) - again} passed at once, "
                     f"{again} asked again, {wrong} still shown with a warning")
    for r in results:
        if r["failed"]:
            lines.append(f"  FAIL {r['id']}  [{r['route']}]")
            lines += [f"       {f}" for f in r["failed"]]
    return lines


def save(results, version, model, directory=RESULTS_DIR):
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    path = os.path.join(directory, f"{version or 'unknown'}_{model.replace(':', '-')}_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": version, "model": model, "when": stamp, "results": results}, f, indent=1)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="only the cases whose id has this in it")
    parser.add_argument("--repeat", type=int, default=1, help="run each case this many times")
    args = parser.parse_args(argv)

    from chat import turn
    from chat.flags import app_version

    cases = [c for c in load_cases() if args.only in c["id"]]
    results = []
    for case in cases:
        for n in range(args.repeat):
            result = run_case(case, turn.respond)
            if args.repeat > 1:
                result["id"] = f"{case['id']} #{n + 1}"
            results.append(result)
            print(f"{'ok  ' if not result['failed'] else 'FAIL'} {result['id']}", flush=True)
    print()
    print("\n".join(summarize(results)))
    print(f"Saved to {save(results, app_version(), CHAT_MODEL)}")
    return 0 if all(not r["failed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
