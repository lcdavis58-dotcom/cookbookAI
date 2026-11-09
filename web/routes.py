"""
The website's chat URLs, all requiring a sign-in. Each account's chats
are in its own folder, so one account has no way to name another's.

Viewing a chat never saves it: a save belongs to the turn that's
answering it (chat/turn.py), which holds the newer copy.
"""

import os
import re

from flask import Blueprint, abort, current_app, redirect, render_template, url_for
from flask_login import current_user, login_required

from chat import store
from chat.router import load_candidates
from chat.state import refresh

# The shape of chat.state.new_id, e.g. 2026-11-06-1932-k4f2.
CHAT_ID = r"\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9]{4}"

bp = Blueprint("chats", __name__)


@bp.before_request
@login_required
def require_login():
    """Every URL here needs a signed-in user."""


def chats_dir():
    """The signed-in user's folder, checked to be directly inside users/."""
    users = os.path.abspath(os.path.join(current_app.config["CHATS_DIR"], "users"))
    folder = os.path.abspath(os.path.join(users, current_user.name))
    if os.path.dirname(folder) != users:
        abort(404)
    return folder


def chat_list():
    """(chats that can be opened, how many saved chats can't be read). A
    file with any other kind of name has no URL, so it isn't listed."""
    summaries = store.list_chats(chats_dir())
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
        chat = store.load(chat_id, chats_dir())
    except store.ChatFileError:
        abort(404)
    candidates = load_candidates()
    # An empty index means it's missing, not that every recipe is gone.
    gone = refresh(chat, candidates) if candidates else []
    chats, broken = chat_list()
    return render_template("chat.html", chats=chats, broken=broken, chat=chat, gone=gone)
