"""
Tests for the version kept with each chat (chat/state.py versions) and
the reliability report (chat/metrics.py, tools/metrics.py), on
temporary folders.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from chat import flags, metrics, store
from chat.state import ChatState
from tools import metrics as tool

CHECKED = {"job": "answer", "model": "qwen2.5:7b", "seconds": 3.0, "checks": []}
FAILED = {"job": "answer", "model": "qwen2.5:7b", "seconds": 3.0, "checks": [{"kind": "quantity", "what": "2 cups"}]}
AGAIN = {"job": "answer again", "model": "qwen2.5:7b", "seconds": 2.0, "checks": []}


def exchange(chat, route, version, seconds=1, calls=()):
    chat.add_user("a message")
    chat.messages[-1].at = "2026-11-25T10:00:00"
    chat.add_reply("a reply", "ask", route, list(calls), version=version)
    chat.messages[-1].at = f"2026-11-25T10:00:{seconds:02d}"


class VersionsTest(unittest.TestCase):
    def test_kept_when_it_changes(self):
        chat = ChatState.new()
        for version in ("1.2.1", "1.2.1", "1.2.2"):
            exchange(chat, "rule: ask find", version)
        self.assertEqual(chat.versions, {"2": "1.2.1", "6": "1.2.2"})
        self.assertEqual([chat.version_of(n) for n in range(1, 7)],
                         [None, "1.2.1", "1.2.1", "1.2.1", "1.2.1", "1.2.2"])

    def test_saved_and_read_back(self):
        chat = ChatState.new()
        exchange(chat, "rule: ask find", "1.2.1")
        self.assertEqual(ChatState.from_dict(json.loads(json.dumps(chat.to_dict()))).versions, {"2": "1.2.1"})

    def test_a_chat_from_before_has_none(self):
        data = ChatState.new().to_dict()
        del data["versions"]
        self.assertEqual(ChatState.from_dict(data).versions, {})

    def test_messages_still_open_in_an_older_version(self):
        # 1.2.0 builds each message with Turn(**t), so a new key on a
        # message would crash it; the versions are kept on the chat.
        chat = ChatState.new()
        exchange(chat, "rule: ask find", "1.2.1", calls=[CHECKED])
        message_keys = {k for m in chat.to_dict()["messages"] for k in m}
        self.assertEqual(message_keys, {"role", "text", "at", "action", "route", "model_calls"})


class MetricsCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.chats = os.path.join(self.dir, "chats")
        self.flags = os.path.join(self.dir, "flags")

    def save(self, chat, account=None):
        store.save(chat, self.chats if account is None else os.path.join(self.chats, "users", account))
        return chat


class RepliesTest(MetricsCase):
    def test_every_account_and_the_terminal(self):
        old = ChatState.new()
        exchange(old, "rule: scale current", None)
        self.save(old)
        new = ChatState.new()
        exchange(new, "model: ask find", "1.2.1", seconds=4, calls=[CHECKED])
        exchange(new, "pending: ask #1", "1.2.1")
        self.save(new, "her")
        found, unreadable = metrics.replies(self.chats)
        self.assertEqual(unreadable, 0)
        self.assertEqual(sorted((r.account, r.version, r.how, r.seconds) for r in found),
                         [("her", "1.2.1", "model", 4.0), ("her", "1.2.1", "pending", 1.0),
                          ("terminal", metrics.UNKNOWN, "rule", 1.0)])

    def test_a_reply_long_after_isnt_a_reply_time(self):
        chat = ChatState.new()
        exchange(chat, "rule: ask find", "1.2.1")
        chat.messages[-1].at = "2026-11-25T11:00:00"
        self.save(chat)
        self.assertIsNone(metrics.replies(self.chats)[0][0].seconds)

    def test_model_misses_and_checks(self):
        replies = [metrics.Reply("a", "c", "1.2.1", label) for label in
                   ("model: reply no tool", "model: reply no tool", "model: reply scale, but no amount",
                    "model: reply ask user", "model: ask filter_recipes, not an ingredient or dish, so answered",
                    "rule: reply filter, no list")]
        unusable, repaired, asked = metrics.model_misses(replies)
        self.assertEqual((dict(unusable), repaired, asked), ({"no tool": 2, "scale, but no amount": 1}, 1, 1))
        checked = [metrics.Reply("a", "c", "1.2.1", "model: ask find", model_calls=calls)
                   for calls in ([CHECKED], [FAILED, AGAIN], [FAILED, FAILED], [])]
        self.assertEqual(metrics.check_counts(checked), (3, 1, 2, 1))


class ReportTest(MetricsCase):
    def test_report_by_version_with_flags(self):
        chat = ChatState.new()
        exchange(chat, "rule: ask find", "1.2.0")
        exchange(chat, "model: ask find", "1.2.1", seconds=5, calls=[FAILED, AGAIN])
        exchange(chat, "model: reply no tool", "1.2.1")
        self.save(chat)
        f = flags.flag(chat, 4, flags.TERMINAL, directory=self.flags)
        f.version = "1.2.1"
        flags.save(f, self.flags)
        old = flags.flag(chat, 2, flags.TERMINAL, directory=self.flags)
        old.version = "1.1.3"
        flags.save(old, self.flags)
        flags.mark_handled(old.id, "1.2.1", self.flags)

        text = "\n".join(metrics.report(self.chats, self.flags))
        self.assertLess(text.index("## 1.2.1"), text.index("## 1.2.0"))
        self.assertLess(text.index("## 1.2.0"), text.index("## 1.1.3"))
        section = text[text.index("## 1.2.1"):text.index("## 1.2.0")]
        self.assertIn("- Replies: 2, in 1 chats (terminal)", section)
        self.assertIn("by the model 2 (100%)", section)
        self.assertIn("couldn't run as called 1, repaired 0, asked her what she meant 0", section)
        self.assertIn("    - no tool: 1", section)
        self.assertIn("- Model answers checked: 1; passed at once 0 (0%), asked again 1, "
                      "still shown with a warning 0", section)
        self.assertIn("- Flagged as wrong: 1, 50.0% of replies; 1 open, 0 handled", section)
        self.assertIn("- Model time, answer again: median 2.0s", section)
        self.assertIn("## 1.1.3\n\n- No replies saved with this version (its replies are counted under "
                      "\"before 1.2.1\")\n- Flagged as wrong: 1; 0 open, 1 handled", text)

    def test_the_tool_writes_the_file(self):
        path = os.path.join(self.dir, "metrics.md")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            tool.main([], chats_dir=self.chats, flags_dir=self.flags, path=path)
        with open(path, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("# Reliability"))
        self.assertIn("Saved to", out.getvalue())

    def test_versions_sort_by_number(self):
        self.assertEqual(sorted(["1.10.0", "1.2.1", metrics.UNKNOWN, "1.2.0"], key=metrics.version_key),
                         [metrics.UNKNOWN, "1.2.0", "1.2.1", "1.10.0"])


if __name__ == "__main__":
    unittest.main()
