"""
Replies flagged as wrong, so bugs found in real use are collected in one
place and can be turned into tests. One JSON file per flag, <id>.json,
in FLAGS_DIR (common/config.py), apart from the chats.

A flag is self-contained: it copies the chat up to and including the
flagged reply, the focus, the app version, the model and when the recipe
index was built. It still says everything after its chat is deleted or
the books are re-ingested.

Keeping flags out of the chat files means a chat's file never changes
when it's flagged, so the chat format stays the same, and flagging never
collides with the website's background worker saving a reply
(web/answers.py).

A flag is "open" until tools/flagged.py marks it "handled", noting what
covers it (a version or a test). summaries() writes the two lists that
tool saves: open_flags.md and handled_flags.md.
"""

import json
import os
import secrets
import string
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

from chat.state import now
from common.config import CHAT_MODEL, FLAGS_DIR, RECIPE_INDEX_PATH

FORMAT = 1
ID_LENGTH = 5
MAX_NOTE_CHARS = 500

# The account terminal chats (chat.py) are flagged under: they have none.
TERMINAL = "terminal"

OPEN, HANDLED = "open", "handled"


class FlagError(Exception):
    """A flag that can't be made, changed or read, with why."""


@dataclass
class Flag:
    id: str
    account: str
    chat_id: str
    chat_title: str
    chat_created: str
    message: int                    # the flagged reply's number, counting from 1
    flagged_at: str
    note: str = ""
    status: str = OPEN
    handled_by: str = ""            # what covers it: a version, a test
    handled_at: str = ""
    # The chat's messages up to and including the flagged reply, as saved
    # (chat.state.Turn: role, text, at, action, route, model_calls).
    messages: list = field(default_factory=list)
    # How many came after it. The focus is the chat's at flag time, so
    # with later messages it's theirs, not the flagged reply's.
    messages_after: int = 0
    focus: dict = field(default_factory=dict)
    version: str = None             # README.md's Version line
    chat_model: str = CHAT_MODEL
    index_built: str = None         # when recipe_index.json was last written

    @property
    def reply(self):
        return self.messages[-1]

    def to_dict(self):
        return {"format": FORMAT, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _new_id():
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(ID_LENGTH))


def app_version():
    """The README's Version line, or None if it can't be read."""
    from tools.check_version import find_versions
    try:
        return find_versions().get("README.md")
    except OSError:
        return None


def index_built(path=RECIPE_INDEX_PATH):
    """When the recipe index was last written, or None if there isn't one.
    A later re-ingest can renumber recipes, and this shows it happened."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
    except OSError:
        return None


# ---- the files ----------------------------------------------------------

def _path(flag_id, directory):
    return os.path.join(directory, f"{flag_id}.json")


def save(flag, directory=FLAGS_DIR):
    os.makedirs(directory, exist_ok=True)
    path = _path(flag.id, directory)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(flag.to_dict(), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise FlagError(f"can't be read ({e})") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        found = data.get("format") if isinstance(data, dict) else None
        raise FlagError(f"saved in format {found!r}, this version reads format {FORMAT}")
    try:
        return Flag.from_dict(data)
    except TypeError as e:
        raise FlagError(f"is missing parts ({e})") from None


def all_flags(directory=FLAGS_DIR):
    """(every readable flag, oldest first; ["<file>: why", ...] for the
    ones that can't be read)."""
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        return [], []
    good, bad = [], []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            good.append(_read(os.path.join(directory, name)))
        except FlagError as e:
            bad.append(f"{name}: {e}")
    good.sort(key=lambda f: (f.flagged_at, f.id))
    return good, bad


def load(flag_id, directory=FLAGS_DIR):
    if not flag_id.isalnum():
        raise FlagError(f"no flag {flag_id!r}")
    if not os.path.exists(_path(flag_id, directory)):
        raise FlagError(f"no flag {flag_id!r}")
    return _read(_path(flag_id, directory))


def for_chat(account, chat_id, directory=FLAGS_DIR):
    """{message number: Flag} for one chat, for showing which replies are
    flagged."""
    flags, _ = all_flags(directory)
    return {f.message: f for f in flags if f.account == account and f.chat_id == chat_id}


def find(account, chat_id, number, directory=FLAGS_DIR):
    return for_chat(account, chat_id, directory).get(number)


# ---- flagging -----------------------------------------------------------

def last_reply(state):
    """The number of the chat's last assistant reply, or None."""
    for i in range(len(state.messages), 0, -1):
        if state.messages[i - 1].role == "assistant":
            return i
    return None


def flag(state, number, account, note="", directory=FLAGS_DIR):
    """Flag reply number (counting from 1) of the chat as wrong. A reply
    already flagged keeps its flag, which is returned unchanged."""
    if not 1 <= number <= len(state.messages) or state.messages[number - 1].role != "assistant":
        raise FlagError(f"message {number} isn't a reply")
    note = note.strip()
    if len(note) > MAX_NOTE_CHARS:
        raise FlagError(f"a note can be up to {MAX_NOTE_CHARS} characters")
    existing = find(account, state.id, number, directory)
    if existing:
        return existing
    new = Flag(
        id=_new_id(), account=account, chat_id=state.id, chat_title=state.title,
        chat_created=state.created, message=number, flagged_at=now(), note=note,
        messages=[asdict(t) for t in state.messages[:number]],
        messages_after=len(state.messages) - number,
        focus=asdict(state.focus), version=app_version(), chat_model=CHAT_MODEL,
        index_built=index_built())
    while os.path.exists(_path(new.id, directory)):
        new.id = _new_id()
    save(new, directory)
    return new


def unflag(account, chat_id, number, directory=FLAGS_DIR):
    """Remove an open flag. False if the reply isn't flagged; FlagError if
    its flag is handled, since that one is kept as a record."""
    existing = find(account, chat_id, number, directory)
    if existing is None:
        return False
    if existing.status == HANDLED:
        raise FlagError("that flag is handled, so it stays")
    os.remove(_path(existing.id, directory))
    return True


def mark_handled(flag_id, handled_by, directory=FLAGS_DIR):
    handled_by = handled_by.strip()
    if not handled_by:
        raise FlagError("say what covers it: a version or a test")
    f = load(flag_id, directory)
    f.status, f.handled_by, f.handled_at = HANDLED, handled_by, now()
    save(f, directory)
    return f


def reopen(flag_id, directory=FLAGS_DIR):
    f = load(flag_id, directory)
    f.status, f.handled_by, f.handled_at = OPEN, "", ""
    save(f, directory)
    return f


# ---- the summaries --------------------------------------------------------

OPEN_FILE = "open_flags.md"
HANDLED_FILE = "handled_flags.md"

# Longer than any run of backticks a reply has, so a reply can't end the block.
FENCE = "````"


def _ref(r):
    return f"{r['title']} ({r['book']})" + (" [gone]" if r.get("gone") else "")


def focus_lines(focus):
    """The focus, one line per part that's set."""
    lines = []
    if focus.get("recipe"):
        lines.append(f"recipe: {_ref(focus['recipe'])}")
    if focus.get("numbered"):
        n = focus["numbered"]
        lines.append(f"numbered ({n['source']}): "
                     + "; ".join(f"{i}. {_ref(r)}" for i, r in enumerate(n["items"], 1)))
    if focus.get("have"):
        lines.append("have: " + ", ".join(focus["have"]))
    if focus.get("scale"):
        s = focus["scale"]
        lines.append(f"scale: {s['factor']:g}x" + (f", batch {s['batch']!r}" if s.get("batch") else ""))
    if focus.get("pending"):
        p = focus["pending"]
        lines.append(f"pending: {p['kind']} for {p['action']}, request {p['request']!r}"
                     + (f", options {', '.join(p['options'])}" if p.get("options") else ""))
    return lines or ["(nothing)"]


def timing(model_calls):
    return ", ".join(f"{c['job']} {c['seconds']:.1f}s" for c in model_calls) or "no model calls"


def entry(f):
    """One flag in a summary file, with the whole chat up to the reply."""
    reply = f.reply
    lines = [f"## {f.id}: \"{f.chat_title or 'New chat'}\" ({f.account})", ""]
    lines.append(f"- Flagged {f.flagged_at}: reply {f.message}, "
                 + (f"{f.messages_after} message{'s' if f.messages_after != 1 else ''} came after it"
                    if f.messages_after else "the last message then"))
    lines.append(f"- Note: {f.note}" if f.note else "- No note")
    if f.status == HANDLED:
        lines.append(f"- Handled {f.handled_at} by: {f.handled_by}")
    lines.append(f"- Route: {reply.get('route') or 'none saved'}; action: {reply.get('action') or 'none'}; "
                 f"{timing(reply.get('model_calls') or [])}")
    lines.append(f"- Version {f.version or 'unknown'}, model {f.chat_model}, "
                 f"recipe index built {f.index_built or 'unknown'}")
    lines.append(f"- Chat {f.chat_id}, started {f.chat_created or 'unknown'}")
    lines += ["", "Focus" + (" (from the later messages, not this reply)" if f.messages_after else "") + ":"]
    lines += [f"    {line}" for line in focus_lines(f.focus)]
    lines.append("")
    for i, t in enumerate(f.messages, 1):
        who = "You" if t["role"] == "user" else "Assistant"
        marker = " **(FLAGGED)**" if i == f.message else ""
        lines += [f"**{i}. {who}**{marker} {t['at']}", "", FENCE, t["text"], FENCE, ""]
    return "\n".join(lines)


def summary(flags, heading, empty):
    lines = [f"# {heading} ({len(flags)})", "",
             f"Written {now()} by tools/flagged.py, oldest first. Mark one handled with",
             '`python tools/flagged.py handled ID "what covers it"`.', ""]
    if not flags:
        lines.append(empty)
    return "\n".join(lines) + "\n" + "\n\n".join(entry(f) for f in flags) + "\n"


def write_summaries(directory=FLAGS_DIR):
    """Rewrite open_flags.md and handled_flags.md from the flags. Returns
    (open flags, handled flags, files that couldn't be read)."""
    flags, bad = all_flags(directory)
    open_ = [f for f in flags if f.status != HANDLED]
    handled = [f for f in flags if f.status == HANDLED]
    os.makedirs(directory, exist_ok=True)
    for name, chosen, heading, empty in (
            (OPEN_FILE, open_, "Open flags", "Nothing flagged."),
            (HANDLED_FILE, handled, "Handled flags", "Nothing handled yet.")):
        path = os.path.join(directory, name)
        with open(f"{path}.tmp", "w", encoding="utf-8") as out:
            out.write(summary(chosen, heading, empty))
        os.replace(f"{path}.tmp", path)
    return open_, handled, bad
