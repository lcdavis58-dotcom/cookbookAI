"""
Reliability numbers from the saved chats and flags (1.2.1), per app
version, for tools/metrics.py:

    routing     how many replies came from rules, an answer to a
                pending question, or the model
    model calls the model's tool calls that couldn't run as called ("no
                tool", "scale, but no amount"...), the ones repaired
                ("not an ingredient or dish, so answered"), and how
                often it asked her what she meant
    times       reply time (her message to the reply, from their
                timestamps) and model time per job
    checks      the model answers checked (actions/answer_checks.py):
                passed at once, asked again, shown with a warning
    flags       replies flagged as wrong, open and handled

A reply's version is the chat's record of it (ChatState.versions);
replies saved before 1.2.1 have none and are counted together.
"""

import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from chat import flags as flag_store
from chat import store
from chat.state import now

FIRST_VERSIONED = "1.2.1"
UNKNOWN = f"before {FIRST_VERSIONED}"
TERMINAL = flag_store.TERMINAL
# Past this, a reply is one answered after a dropped connection (the
# terminal's "answer it now?"), not a reply time.
LONGEST_REPLY = 600


@dataclass
class Reply:
    account: str
    chat_id: str
    version: str
    label: str                      # the route ("model: ask find"), "" if none was saved
    seconds: float = None           # her message to the reply, None when unknown
    model_calls: list = field(default_factory=list)

    @property
    def how(self):
        """"rule", "pending", "model", or "none"."""
        return self.label.split(":", 1)[0] if ":" in self.label else "none"


def chat_folders(chats_dir):
    """[(account, folder)]: the terminal's chats, then each website
    account's (users/<name>/)."""
    folders = [(TERMINAL, chats_dir)]
    users = os.path.join(chats_dir, "users")
    try:
        names = sorted(os.listdir(users))
    except FileNotFoundError:
        names = []
    return folders + [(name, os.path.join(users, name)) for name in names
                      if os.path.isdir(os.path.join(users, name))]


def _seconds(asked, answered):
    try:
        gap = (datetime.fromisoformat(answered) - datetime.fromisoformat(asked)).total_seconds()
    except (TypeError, ValueError):
        return None
    return gap if 0 <= gap <= LONGEST_REPLY else None


def replies(chats_dir):
    """(every saved reply as a Reply, how many chats couldn't be read)."""
    found, unreadable = [], 0
    for account, folder in chat_folders(chats_dir):
        for summary in store.list_chats(folder):
            if summary.error:
                unreadable += 1
                continue
            state = store.load(summary.id, folder)
            asked = None
            for number, turn in enumerate(state.messages, 1):
                if turn.role == "user":
                    asked = turn.at
                    continue
                found.append(Reply(account, state.id, state.version_of(number) or UNKNOWN, turn.route or "",
                                   _seconds(asked, turn.at) if asked else None, list(turn.model_calls or [])))
                asked = None
    return found, unreadable


def version_key(version):
    """For sorting: the unknown version first, then by number."""
    if version == UNKNOWN or not version:
        return (0,)
    try:
        return (1, *(int(p) for p in version.split(".")))
    except ValueError:
        return (2, version)


def _times(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return "none saved"
    return (f"median {statistics.median(values):.1f}s, 90% within {values[int(0.9 * (len(values) - 1))]:.1f}s, "
            f"slowest {values[-1]:.1f}s ({len(values)})")


def _pct(n, total):
    return f"{n} ({100 * n / total:.0f}%)" if total else str(n)


def model_misses(replies_):
    """(Counter of the model's calls that couldn't run as called, by the
    route's detail; how many were repaired; how many asked her)."""
    unusable, repaired, asked = Counter(), 0, 0
    for r in replies_:
        if r.label == "model: reply ask user":
            asked += 1
        elif r.label.startswith("model: reply"):
            unusable[r.label[len("model: reply "):]] += 1
        elif r.label.startswith("model:") and "so answered" in r.label:
            repaired += 1
    return unusable, repaired, asked


def check_counts(replies_):
    """(answers checked, passed at once, asked again, still shown with a
    warning), from the "checks" saved with each model call."""
    checked = at_once = again = warned = 0
    for r in replies_:
        results = [c["checks"] for c in r.model_calls if "checks" in c]
        if not results:
            continue
        checked += 1
        at_once += not results[0]
        again += len(results) > 1
        warned += bool(results[-1])
    return checked, at_once, again, warned


def version_section(version, replies_, flags_):
    lines = [f"## {version}", ""]
    total = len(replies_)
    if total:
        how = Counter(r.how for r in replies_)
        chats = len({(r.account, r.chat_id) for r in replies_})
        accounts = sorted({r.account for r in replies_})
        lines += [f"- Replies: {total}, in {chats} chats ({', '.join(accounts)})",
                  f"- Routed by rules {_pct(how['rule'], total)}, by an answer to a pending question "
                  f"{_pct(how['pending'], total)}, by the model {_pct(how['model'], total)}"
                  + (f", not saved {how['none']}" if how["none"] else "")]
        unusable, repaired, asked = model_misses(replies_)
        lines.append(f"- Model routes: {how['model']}; couldn't run as called {sum(unusable.values())}, "
                     f"repaired {repaired}, asked her what she meant {asked}")
        lines += [f"    - {detail}: {n}" for detail, n in unusable.most_common()]
        lines.append(f"- Reply time: {_times(r.seconds for r in replies_)}")
        by_job = defaultdict(list)
        for r in replies_:
            for call in r.model_calls:
                by_job[call.get("job", "?")].append(call.get("seconds"))
        for job in sorted(by_job):
            lines.append(f"- Model time, {job}: {_times(by_job[job])}")
        checked, at_once, again, warned = check_counts(replies_)
        if checked:
            lines.append(f"- Model answers checked: {checked}; passed at once {_pct(at_once, checked)}, "
                         f"asked again {again}, still shown with a warning {warned}")
    else:
        older = version_key(version) < version_key(FIRST_VERSIONED)
        lines.append("- No replies saved with this version"
                     + (f" (its replies are counted under \"{UNKNOWN}\")" if older else ""))
    handled = sum(1 for f in flags_ if f.status == flag_store.HANDLED)
    share = f", {100 * len(flags_) / total:.1f}% of replies" if total and flags_ else ""
    lines.append(f"- Flagged as wrong: {len(flags_)}{share}"
                 + (f"; {len(flags_) - handled} open, {handled} handled" if flags_ else ""))
    return lines


def report(chats_dir, flags_dir):
    """The report's lines (markdown), newest version first."""
    found, unreadable = replies(chats_dir)
    flags_, bad_flags = flag_store.all_flags(flags_dir)
    by_version = defaultdict(list)
    for r in found:
        by_version[r.version].append(r)
    flags_by_version = defaultdict(list)
    for f in flags_:
        flags_by_version[f.version or UNKNOWN].append(f)
    lines = ["# Reliability", "", f"Written {now()} by tools/metrics.py from {len(found)} replies and "
             f"{len(flags_)} flags. Replies saved before 1.2.1 have no version and are counted together; "
             "flags always had one.", ""]
    if unreadable or bad_flags:
        lines += [f"Couldn't read {unreadable} chats and {len(bad_flags)} flags.", ""]
    for version in sorted(set(by_version) | set(flags_by_version), key=version_key, reverse=True):
        lines += version_section(version, by_version[version], flags_by_version[version]) + [""]
    return lines


def write(path, chats_dir, flags_dir):
    """Write the report to path (atomically). Returns its lines."""
    lines = report(chats_dir, flags_dir)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(f"{path}.tmp", "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    os.replace(f"{path}.tmp", path)
    return lines
