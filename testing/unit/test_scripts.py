"""
Tests for the command-line scripts (chat.py, serve.py, query.py,
scale.py, match.py): each one is run as a script with made-up arguments,
with the work it hands off to (the actions, the terminal chat, the web
server) replaced by stand-ins. Checks that the arguments reach the right
place; what the actions themselves do is tested in test_actions.py.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import io
import os
import runpy
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

import waitress  # noqa: E402

import web  # noqa: E402
from actions import ask, match, scale  # noqa: E402
from chat import terminal  # noqa: E402
from common import accounts, cli  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def run_script(name, *args):
    """Run a script as `python3 name args...`; returns what it printed."""
    out = io.StringIO()
    with mock.patch.object(sys, "argv", [name, *args]), redirect_stdout(out):
        runpy.run_path(os.path.join(ROOT, name), run_name="__main__")
    return out.getvalue()


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, cli, "DEBUG", cli.DEBUG)
        cli.DEBUG = False


class OneShotScriptsTest(ScriptTest):
    """query.py, scale.py and match.py: run the action, print it."""

    def check(self, script, action, *args):
        with mock.patch.object(action, "run", return_value="result") as run, \
                mock.patch.object(action, "render", return_value="rendered") as render:
            out = run_script(script, *args)
        render.assert_called_once_with("result")
        self.assertEqual(out, "rendered\n")
        return run

    def test_query(self):
        run = self.check("query.py", ask, "what", "page", "has", "pie?")
        run.assert_called_once_with("what page has pie?")
        self.assertFalse(cli.DEBUG)

    def test_scale_with_debug(self):
        run = self.check("scale.py", scale, "-d", "double the pie")
        run.assert_called_once_with("double the pie")
        self.assertTrue(cli.DEBUG)

    def test_match_words_are_joined(self):
        run = self.check("match.py", match, "pecans,", "cream", "cheese")
        run.assert_called_once_with("pecans, cream cheese")

    def test_question_is_required(self):
        with mock.patch.object(ask, "run") as run, mock.patch("sys.stderr", io.StringIO()), \
                self.assertRaises(SystemExit):
            run_script("query.py")
        run.assert_not_called()


class ChatScriptTest(ScriptTest):
    def run_chat(self, *args):
        with mock.patch.object(terminal, "Terminal") as cls:
            run_script("chat.py", *args)
        return cls.return_value

    def test_plain_start(self):
        t = self.run_chat()
        t.run.assert_called_once_with(new=False, open_ref=None)
        self.assertFalse(cli.DEBUG)

    def test_new_with_debug(self):
        t = self.run_chat("--new", "-d")
        t.run.assert_called_once_with(new=True, open_ref=None)
        self.assertTrue(cli.DEBUG)

    def test_open(self):
        self.run_chat("--open", "3").run.assert_called_once_with(new=False, open_ref="3")

    def test_list(self):
        t = self.run_chat("--list")
        t.list_chats.assert_called_once_with()
        t.run.assert_not_called()

    def test_new_and_list_together_are_refused(self):
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            self.run_chat("--new", "--list")


class ServeScriptTest(ScriptTest):
    def run_serve(self, *args, users=("levi",)):
        with mock.patch.object(waitress, "serve") as serve, \
                mock.patch.object(web, "create_app", return_value="app") as create_app, \
                mock.patch.object(accounts, "load", return_value=list(users)):
            out = run_script("serve.py", *args)
        return out, serve, create_app

    def test_defaults_to_this_computer_only(self):
        out, serve, create_app = self.run_serve()
        serve.assert_called_once_with("app", host="127.0.0.1", port=8000)
        create_app.assert_called_once_with(https=False)
        self.assertEqual(out, "Listening on 127.0.0.1:8000 (Ctrl+C to stop)\n")

    def test_lan_https_and_port(self):
        _, serve, create_app = self.run_serve("--lan", "--https", "--port", "8080")
        serve.assert_called_once_with("app", host="0.0.0.0", port=8080)
        create_app.assert_called_once_with(https=True)

    def test_warns_when_there_are_no_accounts(self):
        out, serve, _ = self.run_serve(users=())
        self.assertIn("No accounts yet", out)
        serve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
