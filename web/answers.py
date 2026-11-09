"""
Replies are worked out in the background, one at a time, so a reply
doesn't depend on the browser staying connected: a locked phone or lost
signal changes nothing here, and the page picks the saved reply up when
it next checks.

While a chat has a reply being worked on, this worker owns its file and
nothing else may save it (submit refuses). What's being worked on is
kept in memory: after a restart, a message left without a reply is
simply unanswered, and the page offers to answer it.
"""

import logging
import queue
import threading
import time

from chat import store, turn
from chat.router import load_candidates
from chat.state import refresh
from common import models

log = logging.getLogger(__name__)

NO_MODEL = "I couldn't reach the model. It may not be running."
TOO_SLOW = "The model took too long to answer."
WENT_WRONG = "Something went wrong answering this."


def answer_chat(directory, chat_id):
    """Answer the chat's unanswered message, saving the reply."""
    chat = store.load(chat_id, directory)
    candidates = load_candidates()
    # An empty index means it's missing, not that every recipe is gone.
    if candidates:
        refresh(chat, candidates)
    turn.retry(chat, directory, candidates)


def failure_text(error):
    if models.is_connection_error(error):
        return NO_MODEL
    if models.is_timeout(error):
        return TOO_SLOW
    return WENT_WRONG


class Answers:
    def __init__(self, work):
        self.work = work
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.started = {}           # (directory, chat id) -> when it was submitted
        self.failures = {}          # (directory, chat id) -> what to tell her
        self.thread = None

    def submit(self, directory, chat_id, before=None):
        """Queue a reply for the chat, first running before() (which saves
        her message). False, with before() not run, if one is already
        being worked on."""
        key = (directory, chat_id)
        with self.lock:
            if key in self.started:
                return False
            if before:
                before()
            self.started[key] = time.monotonic()
            self.failures.pop(key, None)
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name="answers")
                self.thread.start()
        self.queue.put(key)
        return True

    def seconds_working(self, directory, chat_id):
        """How long this chat's reply has been in progress, None if it isn't."""
        with self.lock:
            started = self.started.get((directory, chat_id))
        return None if started is None else time.monotonic() - started

    def failure(self, directory, chat_id):
        with self.lock:
            return self.failures.get((directory, chat_id))

    def join(self):
        """Wait until everything queued is finished (for tests)."""
        self.queue.join()

    def _run(self):
        while True:
            key = self.queue.get()
            failure = None
            try:
                self.work(*key)
            except Exception as e:  # noqa: BLE001 -- the worker has to survive any one chat
                log.exception("Couldn't answer chat %s", key[1])
                failure = failure_text(e)
            with self.lock:
                if failure:
                    self.failures[key] = failure
                del self.started[key]
            self.queue.task_done()
