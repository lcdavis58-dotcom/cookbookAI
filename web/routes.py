"""
The website's URLs. Viewing a chat never saves it: a save belongs to the
turn that's answering it (chat/turn.py), which holds the newer copy.
"""

import re

from flask import Blueprint, abort, current_app, redirect, render_template, url_for

from chat import store
from chat.router import load_candidates
from chat.state import refresh

# The shape of chat.state.new_id, e.g. 2026-11-06-1932-k4f2.
CHAT_ID = r"\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9]{4}"

bp = Blueprint("chats", __name__)


def chat_list():
    """(chats that can be opened, how many saved chats can't be read). A
    file with any other kind of name has no URL, so it isn't listed."""
    summaries = store.list_chats(current_app.config["CHATS_DIR"])
    readable = [c for c in summaries if c.error is None and re.fullmatch(CHAT_ID, c.id)]
    return readable, sum(1 for c in summaries if c.error)


@bp.get("/")
def index():
    chats, broken = chat_list()
    if chats:
        return redirect(url_for("chats.show", chat_id=chats[0].id))
    return render_template("chat.html", chats=chats, broken=broken, chat=None, gone=[])


@bp.get("/chats/<chat_id:chat_id>")
def show(chat_id):
    try:
        chat = store.load(chat_id, current_app.config["CHATS_DIR"])
    except store.ChatFileError:
        abort(404)
    candidates = load_candidates()
    # An empty index means it's missing, not that every recipe is gone.
    gone = refresh(chat, candidates) if candidates else []
    chats, broken = chat_list()
    return render_template("chat.html", chats=chats, broken=broken, chat=chat, gone=gone)
