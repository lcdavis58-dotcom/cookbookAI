"""
The website: the same chat as chat.py, in a browser. This package only
handles web requests and pages; everything about answering a message
stays in chat/ and actions/.

    routes.py       the URLs
    templates/      the pages
"""

from flask import Flask, render_template
from werkzeug.routing import BaseConverter

from chat.terminal import when
from common.config import CHATS_DIR
from web.routes import CHAT_ID, bp


class ChatIdConverter(BaseConverter):
    """Only a well-formed chat id reaches a route. An id becomes a file
    name (chat/store.py), and Flask's normal text match allows backslashes,
    which on Windows could climb out of the chats folder."""
    regex = CHAT_ID


def create_app(chats_dir=CHATS_DIR):
    app = Flask(__name__)
    app.config["CHATS_DIR"] = chats_dir
    app.url_map.converters["chat_id"] = ChatIdConverter
    app.jinja_env.filters["when"] = when
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("not_found.html"), 404

    return app
