"""
The website's chat URLs, all requiring a sign-in. Each account's chats
are in its own folder, so one account has no way to name another's.

Sending a message takes two parts: the POST saves it and hands it to the
background worker (web/answers.py), then the page asks /status every two
seconds until the reply is saved. The #status element at the end of the
conversation is what those requests replace.

Only the worker saves a chat while it's answering, so viewing never
saves, and a new message is refused until the reply is done.
"""

import os
import re

from flask import (Blueprint, abort, current_app, make_response, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from chat import store
from chat.router import load_candidates
from chat.state import ChatState, refresh

# The shape of chat.state.new_id, e.g. 2026-11-06-1932-k4f2.
CHAT_ID = r"\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9]{4}"
MAX_MESSAGE_CHARS = 4000
SLOW_AFTER_SECONDS = 30

bp = Blueprint("chats", __name__)


@bp.before_request
@login_required
def require_login():
    """Every URL here needs a signed-in user."""


@bp.context_processor
def limits():
    return {"max_message_chars": MAX_MESSAGE_CHARS}


def chats_dir():
    """The signed-in user's folder, checked to be directly inside users/."""
    users = os.path.abspath(os.path.join(current_app.config["CHATS_DIR"], "users"))
    folder = os.path.abspath(os.path.join(users, current_user.name))
    if os.path.dirname(folder) != users:
        abort(404)
    return folder


def answers():
    return current_app.extensions["answers"]


def chat_list():
    """(chats that can be opened, how many saved chats can't be read). A
    file with any other kind of name has no URL, so it isn't listed."""
    summaries = store.list_chats(chats_dir())
    readable = [c for c in summaries if c.error is None and re.fullmatch(CHAT_ID, c.id)]
    return readable, sum(1 for c in summaries if c.error)


def load_chat(chat_id):
    try:
        return store.load(chat_id, chats_dir())
    except store.ChatFileError:
        abort(404)


def message_text():
    """The message in the form, or "add ..." from the ingredient box. The
    page's own limits already refuse bad ones, so this only stops
    hand-made requests."""
    add = request.form.get("add", "").strip()
    text = f"add {add}" if add else request.form.get("message", "").strip()
    if not text or len(text) > MAX_MESSAGE_CHARS:
        abort(400)
    return text


def quick_replies(chat):
    """What can be tapped under the latest reply, each sending the message
    she could have typed:
        numbers     (n, recipe) for a "which one?" list or match results
        batches     the batch sizes it's asking her to pick from
        have        the ingredients just searched, to remove or add to"""
    if not chat.messages or chat.messages[-1].role != "assistant":
        return {}
    focus, action = chat.focus, chat.messages[-1].action
    if focus.pending and focus.pending.kind == "pick_batch":
        return {"batches": focus.pending.options}
    numbered = list(enumerate(focus.numbered.items, 1)) if focus.numbered else []
    if focus.pending and focus.pending.kind == "pick_recipe":
        return {"numbers": numbered}
    if action == "match" and not focus.pending and focus.have:
        return {"numbers": numbered if focus.numbered.source == "match" else [], "have": focus.have}
    return {}


def status_of(chat_id):
    """What #status should say: (the chat, template values). Checks the
    worker before reading the file, so a reply finishing in between is
    found on the next check instead of looking unanswered."""
    seconds = answers().seconds_working(chats_dir(), chat_id)
    chat = load_chat(chat_id)
    return chat, {"working": seconds is not None,
                  "slow": seconds is not None and seconds > SLOW_AFTER_SECONDS,
                  "unanswered": chat.unanswered() is not None,
                  "failure": answers().failure(chats_dir(), chat_id),
                  "quick": {} if seconds is not None else quick_replies(chat)}


def status_response(chat_id, deliver_reply=False):
    """The new #status. deliver_reply: the page is waiting on a reply, so
    if it's done, include it and scroll to its start."""
    chat, status = status_of(chat_id)
    finished = deliver_reply and not status["working"] and not status["unanswered"] and chat.messages
    response = make_response(render_template(
        "_status.html", chat=chat, status=status, oob=True,
        reply=chat.messages[-1] if finished else None, number=len(chat.messages)))
    if finished:
        response.headers["HX-Reswap"] = f"outerHTML show:#m{len(chat.messages)}:top"
    return response


@bp.get("/")
def index():
    chats, broken = chat_list()
    if chats:
        return redirect(url_for("chats.show", chat_id=chats[0].id))
    return render_template("chat.html", chats=chats, broken=broken, chat=None, gone=[], status=None)


@bp.get("/chats/new")
def new():
    chats, broken = chat_list()
    return render_template("chat.html", chats=chats, broken=broken, chat=None, gone=[], status=None)


@bp.post("/chats")
def create():
    """Start a chat with its first message, then open it."""
    chat = ChatState.new()
    chat.add_user(message_text())
    answers().submit(chats_dir(), chat.id, before=lambda: store.save(chat, chats_dir()))
    response = make_response("", 204)
    response.headers["HX-Redirect"] = url_for("chats.show", chat_id=chat.id)
    return response


@bp.get("/chats/<chat_id:chat_id>")
def show(chat_id):
    chat, status = status_of(chat_id)
    candidates = load_candidates()
    # An empty index means it's missing, not that every recipe is gone.
    gone = refresh(chat, candidates) if candidates else []
    chats, broken = chat_list()
    return render_template("chat.html", chats=chats, broken=broken, chat=chat, gone=gone, status=status)


@bp.post("/chats/<chat_id:chat_id>/messages")
def send(chat_id):
    """Save her message and start on the reply. Returns her message, for
    the conversation, followed by the "thinking" status."""
    text = message_text()
    folder = chats_dir()

    def save():
        chat = load_chat(chat_id)
        chat.add_user(text)
        store.save(chat, folder)

    if not answers().submit(folder, chat_id, before=save):
        return status_response(chat_id)     # a reply is in progress; her text stays in the box
    chat, status = status_of(chat_id)
    # Only the message form empties the message box: tapping a button
    # mustn't lose something she was in the middle of typing.
    return render_template("_sent.html", chat=chat, status=status, oob=True, message=chat.messages[-1],
                           number=len(chat.messages), clear_box=request.headers.get("HX-Trigger") == "composer")


@bp.post("/chats/<chat_id:chat_id>/answer")
def answer(chat_id):
    """The "Answer it now" button. If the reply turns out to exist
    already, it's returned instead of being answered twice."""
    if load_chat(chat_id).unanswered() is not None:
        answers().submit(chats_dir(), chat_id)
    return status_response(chat_id, deliver_reply=True)


@bp.get("/chats/<chat_id:chat_id>/status")
def status(chat_id):
    return status_response(chat_id, deliver_reply=True)
