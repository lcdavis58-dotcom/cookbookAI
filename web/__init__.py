"""
The website: the same chat as chat.py, in a browser. This package only
handles web requests and pages; everything about answering a message
stays in chat/ and actions/.

    auth.py         signing in and out
    routes.py       the chat URLs
    templates/      the pages
"""

import os
import secrets
from datetime import timedelta

from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.routing import BaseConverter

from chat.terminal import when
from common.config import CHATS_DIR, USERS_PATH, WEB_SECRET_PATH
from web import auth
from web.routes import CHAT_ID, bp

MAX_REQUEST_BYTES = 64 * 1024

# What the browser may load and where a page may send things: only this
# site, no inline scripts or styles, and no framing by other sites.
CONTENT_SECURITY_POLICY = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
                           "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


class ChatIdConverter(BaseConverter):
    """Only a well-formed chat id reaches a route. An id becomes a file
    name (chat/store.py), and Flask's normal text match allows backslashes,
    which on Windows could climb out of the chats folder."""
    regex = CHAT_ID


def secret_key(path):
    """The key that signs login cookies, created on first use. It stays
    the same across restarts, so nobody is signed out by one."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "xb") as f:
            f.write(key)
        return key


def create_app(chats_dir=CHATS_DIR, users_path=USERS_PATH, secret_path=WEB_SECRET_PATH,
               https=False, config=None):
    """https: the site is reached over HTTPS (through Cloudflare, say), so
    the login cookie must never be sent without it."""
    app = Flask(__name__)
    app.config.update(
        CHATS_DIR=chats_dir,
        USERS_PATH=users_path,
        SECRET_KEY=secret_key(secret_path),
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=https,
        # A page left open for hours must still work; the token lasts as
        # long as the login does.
        WTF_CSRF_TIME_LIMIT=None,
        **(config or {}),
    )
    app.url_map.converters["chat_id"] = ChatIdConverter
    app.jinja_env.filters["when"] = when
    CSRFProtect(app)
    auth.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(bp)

    def error_page(status, heading, detail):
        return render_template("error.html", heading=heading, detail=detail), status

    @app.errorhandler(404)
    def not_found(_error):
        return error_page(404, "That page isn't here", "")

    @app.errorhandler(CSRFError)
    def bad_token(_error):
        return error_page(400, "That page was out of date", "Go back, reload the page and try again.")

    @app.errorhandler(413)
    def too_large(_error):
        return error_page(413, "That was too long", "Go back and send something shorter.")

    @app.errorhandler(500)
    def server_error(_error):
        return error_page(500, "Something went wrong", "Try again in a moment.")

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.endpoint != "static":
            # Keeps private chats out of browser and proxy caches.
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
