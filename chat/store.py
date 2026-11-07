"""
Saved chats: one JSON file per chat, <id>.json, in CHATS_DIR
(common/config.py), a folder holding nothing but chats. A chat is meant
to be saved when her message arrives and again with the reply, so a
dropped connection loses nothing she typed (ChatState.unanswered finds a
message left without a reply).

Each save writes a temporary file and swaps it in, so a crash mid-save
leaves the previous version, never half a file. A file that can't be
read is listed with its error and never stops the others from loading.
"""

import json
import os
from dataclasses import dataclass

from chat.state import FORMAT, ChatState
from common.config import CHATS_DIR


class ChatFileError(Exception):
    """A saved chat that can't be read."""


@dataclass
class ChatSummary:
    id: str
    title: str = ""
    updated: str = ""
    message_count: int = 0
    error: str = None               # why it couldn't be read, if it couldn't


def _path(chat_id, directory):
    return os.path.join(directory, f"{chat_id}.json")


def save(state, directory=CHATS_DIR):
    os.makedirs(directory, exist_ok=True)
    path = _path(state.id, directory)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ChatFileError("no chat by that name") from None
    except (OSError, ValueError) as e:
        raise ChatFileError(f"can't be read ({e})") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        found = data.get("format") if isinstance(data, dict) else None
        raise ChatFileError(f"saved in format {found!r}, this version reads format {FORMAT}")
    try:
        return ChatState.from_dict(data)
    except (KeyError, TypeError) as e:
        raise ChatFileError(f"is missing parts ({e})") from None


def load(chat_id, directory=CHATS_DIR):
    """The saved chat, or ChatFileError saying why it can't be read."""
    return _read(_path(chat_id, directory))


def delete(chat_id, directory=CHATS_DIR):
    try:
        os.remove(_path(chat_id, directory))
    except FileNotFoundError:
        pass


def list_chats(directory=CHATS_DIR):
    """Every saved chat, most recently updated first. Unreadable ones come
    last, with error set."""
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    good, bad = [], []
    for name in names:
        if not name.endswith(".json"):
            continue
        chat_id = name[:-len(".json")]
        try:
            state = _read(os.path.join(directory, name))
        except ChatFileError as e:
            bad.append(ChatSummary(chat_id, error=str(e)))
            continue
        good.append(ChatSummary(chat_id, state.title, state.updated, len(state.messages)))
    good.sort(key=lambda s: (s.updated, s.id), reverse=True)
    return good + sorted(bad, key=lambda s: s.id)


def latest(directory=CHATS_DIR):
    """The most recently updated chat that can be read, or None."""
    for summary in list_chats(directory):
        if summary.error is None:
            return load(summary.id, directory)
    return None
