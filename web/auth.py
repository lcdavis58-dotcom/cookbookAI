"""
Signing in and out. Accounts themselves are in common/accounts.py.

Repeated wrong passwords make a user name wait, and every failure gets
the same message, so the page never reveals which user names exist.
"""

import hmac
import threading
import time

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user

from common import accounts

FAILURE_LIMIT = 5
WAIT_SECONDS = 60
MOST_TRACKED = 1000                 # names remembered, so junk can't fill memory

bp = Blueprint("auth", __name__)
login_manager = LoginManager()


class User(UserMixin):
    def __init__(self, name, password_hash):
        self.name = name
        self.password_hash = password_hash

    def get_id(self):
        return f"{self.name}:{accounts.stamp(self.password_hash)}"


class Throttle:
    """After FAILURE_LIMIT wrong passwords, a user name waits WAIT_SECONDS."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.failures = {}          # name -> wrong tries so far
        self.waiting = {}           # name -> when it may try again

    def blocked(self, name):
        with self.lock:
            return self.waiting.get(name, 0) > self.clock()

    def failed(self, name):
        with self.lock:
            if len(self.failures) >= MOST_TRACKED or len(self.waiting) >= MOST_TRACKED:
                self.failures.clear()
                self.waiting.clear()
            self.failures[name] = self.failures.get(name, 0) + 1
            if self.failures[name] >= FAILURE_LIMIT:
                self.failures[name] = 0
                self.waiting[name] = self.clock() + WAIT_SECONDS

    def clear(self, name):
        with self.lock:
            self.failures.pop(name, None)
            self.waiting.pop(name, None)


def init_app(app):
    app.extensions["login_throttle"] = Throttle()
    login_manager.init_app(app)


@login_manager.user_loader
def load_user(session_id):
    name, _, stamp = session_id.partition(":")
    password_hash = accounts.load(current_app.config["USERS_PATH"]).get(name)
    if password_hash and hmac.compare_digest(stamp, accounts.stamp(password_hash)):
        return User(name, password_hash)
    return None


@login_manager.unauthorized_handler
def go_to_login():
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("chats.index"))
    if request.method == "GET":
        return render_template("login.html", failed=False)
    name = accounts.normalize(request.form.get("username", ""))
    password = request.form.get("password", "")
    path = current_app.config["USERS_PATH"]
    throttle = current_app.extensions["login_throttle"]
    if not throttle.blocked(name):
        if accounts.check(name, password, path):
            throttle.clear(name)
            session.clear()
            login_user(User(name, accounts.load(path)[name]))
            session.permanent = True    # lasts PERMANENT_SESSION_LIFETIME
            return redirect(url_for("chats.index"))
        throttle.failed(name)
    return render_template("login.html", failed=True), 401


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
