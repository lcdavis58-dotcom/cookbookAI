"""
Tests for flagging replies as wrong (chat/flags.py) and the review tool
(tools/flagged.py), on temporary folders.

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
from unittest import mock

from chat import flags
from chat.state import ChatState, Numbered, Pending, RecipeRef, ScaleUsed
from tools import flagged as tool


def chat_with(*texts):
    """A chat whose messages alternate hers and replies, starting with hers."""
    chat = ChatState.new()
    for i, text in enumerate(texts):
        if i % 2 == 0:
            chat.add_user(text)
        else:
            chat.add_reply(text, action="scale", route="rule: scale current",
                           model_calls=[{"job": "route", "model": "qwen2.5:7b", "seconds": 1.25}])
    return chat


class FlagCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)


class FlaggingTest(FlagCase):
    def test_a_flag_holds_everything_to_understand_it(self):
        chat = chat_with("double the whipped cream", "Scaled it.", "now halve it", "Halved.")
        chat.focus.recipe = RecipeRef("12", "Dessert Person", "Whipped Cream")
        chat.focus.scale = ScaleUsed(1.0)
        with mock.patch("chat.flags.app_version", return_value="1.1.0"), \
             mock.patch("chat.flags.index_built", return_value="2026-11-14T10:00:00"):
            f = flags.flag(chat, 2, "levi", "  it tripled it  ", self.dir)

        saved = flags.load(f.id, self.dir)
        self.assertEqual(saved, f)
        self.assertEqual((saved.account, saved.chat_id, saved.chat_title), ("levi", chat.id, chat.title))
        self.assertEqual(saved.chat_created, chat.created)
        self.assertEqual(saved.message, 2)
        self.assertEqual(saved.note, "it tripled it")
        self.assertEqual(saved.status, flags.OPEN)
        self.assertEqual([m["text"] for m in saved.messages], ["double the whipped cream", "Scaled it."])
        self.assertEqual(saved.reply["route"], "rule: scale current")
        self.assertEqual(saved.reply["model_calls"][0]["seconds"], 1.25)
        self.assertEqual(saved.messages_after, 2)
        self.assertEqual(saved.focus["recipe"]["title"], "Whipped Cream")
        self.assertEqual(saved.focus["scale"]["factor"], 1.0)
        self.assertEqual((saved.version, saved.index_built), ("1.1.0", "2026-11-14T10:00:00"))
        self.assertTrue(saved.chat_model)

    def test_the_chat_file_is_not_needed_afterwards(self):
        chat = chat_with("hi", "Hello.")
        f = flags.flag(chat, 2, "levi", directory=self.dir)
        del chat
        self.assertEqual(flags.load(f.id, self.dir).reply["text"], "Hello.")

    def test_only_replies_can_be_flagged(self):
        chat = chat_with("hi", "Hello.")
        for number in (0, 1, 3):
            with self.assertRaises(flags.FlagError):
                flags.flag(chat, number, "levi", directory=self.dir)

    def test_a_note_too_long_is_refused(self):
        with self.assertRaises(flags.FlagError):
            flags.flag(chat_with("hi", "Hello."), 2, "levi", "x" * (flags.MAX_NOTE_CHARS + 1), self.dir)

    def test_flagging_again_keeps_the_first_flag(self):
        chat = chat_with("hi", "Hello.")
        first = flags.flag(chat, 2, "levi", "wrong", self.dir)
        again = flags.flag(chat, 2, "levi", "other", self.dir)
        self.assertEqual(again.id, first.id)
        self.assertEqual(again.note, "wrong")
        self.assertEqual(len(flags.all_flags(self.dir)[0]), 1)

    def test_flags_belong_to_an_account(self):
        chat = chat_with("hi", "Hello.")
        flags.flag(chat, 2, "levi", directory=self.dir)
        self.assertIsNone(flags.find("tester", chat.id, 2, self.dir))
        self.assertEqual(set(flags.for_chat("levi", chat.id, self.dir)), {2})
        self.assertEqual(flags.for_chat("levi", "other-chat", self.dir), {})

    def test_last_reply(self):
        self.assertIsNone(flags.last_reply(ChatState.new()))
        self.assertIsNone(flags.last_reply(chat_with("hi")))
        self.assertEqual(flags.last_reply(chat_with("hi", "Hello.", "and?")), 2)

    def test_the_version_comes_from_the_readme(self):
        self.assertRegex(flags.app_version(), r"^\d+\.\d+\.\d+$")

    def test_index_built_is_none_without_an_index(self):
        self.assertIsNone(flags.index_built(os.path.join(self.dir, "none.json")))
        path = os.path.join(self.dir, "index.json")
        open(path, "w").close()
        self.assertRegex(flags.index_built(path), r"^\d{4}-\d{2}-\d{2}T")


class ChangingTest(FlagCase):
    def setUp(self):
        super().setUp()
        self.chat = chat_with("hi", "Hello.")
        self.f = flags.flag(self.chat, 2, "levi", directory=self.dir)

    def test_unflag(self):
        self.assertTrue(flags.unflag("levi", self.chat.id, 2, self.dir))
        self.assertEqual(flags.all_flags(self.dir), ([], []))
        self.assertFalse(flags.unflag("levi", self.chat.id, 2, self.dir))

    def test_a_handled_flag_cant_be_unflagged(self):
        flags.mark_handled(self.f.id, "1.1.2", self.dir)
        with self.assertRaises(flags.FlagError):
            flags.unflag("levi", self.chat.id, 2, self.dir)
        self.assertIsNotNone(flags.find("levi", self.chat.id, 2, self.dir))

    def test_handled_and_reopened(self):
        done = flags.mark_handled(self.f.id, " test_x.HalfAndHalf ", self.dir)
        self.assertEqual((done.status, done.handled_by), (flags.HANDLED, "test_x.HalfAndHalf"))
        self.assertTrue(done.handled_at)
        again = flags.reopen(self.f.id, self.dir)
        self.assertEqual((again.status, again.handled_by, again.handled_at), (flags.OPEN, "", ""))

    def test_handled_needs_what_covers_it(self):
        with self.assertRaises(flags.FlagError):
            flags.mark_handled(self.f.id, "  ", self.dir)

    def test_unknown_or_odd_ids(self):
        for flag_id in ("nope1", "../x", ""):
            with self.assertRaises(flags.FlagError):
                flags.load(flag_id, self.dir)

    def test_an_unreadable_flag_is_reported_and_skipped(self):
        with open(os.path.join(self.dir, "bad01.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(self.dir, "old01.json"), "w") as f:
            json.dump({"format": 99}, f)
        good, bad = flags.all_flags(self.dir)
        self.assertEqual([f.id for f in good], [self.f.id])
        self.assertEqual(len(bad), 2)

    def test_a_newer_flag_with_extra_parts_still_reads(self):
        path = os.path.join(self.dir, f"{self.f.id}.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["something_new"] = 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(flags.load(self.f.id, self.dir).id, self.f.id)

    def test_no_folder_yet(self):
        self.assertEqual(flags.all_flags(os.path.join(self.dir, "missing")), ([], []))


class SummaryTest(FlagCase):
    def read(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return f.read()

    def test_open_and_handled_go_to_their_own_files(self):
        a = flags.flag(chat_with("double the whipped cream", "Tripled it."), 2, "levi", "tripled", self.dir)
        b = flags.flag(chat_with("hi", "Hello."), 2, "tester", directory=self.dir)
        flags.mark_handled(b.id, "1.1.2", self.dir)
        open_, handled, bad = flags.write_summaries(self.dir)
        self.assertEqual(([f.id for f in open_], [f.id for f in handled], bad), ([a.id], [b.id], []))

        text = self.read(flags.OPEN_FILE)
        self.assertIn("# Open flags (1)", text)
        self.assertIn(f"## {a.id}", text)
        self.assertIn("(levi)", text)
        self.assertIn("Note: tripled", text)
        self.assertIn("rule: scale current", text)
        self.assertIn("route 1.2s", text)
        self.assertIn("double the whipped cream", text)
        self.assertIn("**2. Assistant** **(FLAGGED)**", text)
        self.assertNotIn(b.id, text)

        text = self.read(flags.HANDLED_FILE)
        self.assertIn("# Handled flags (1)", text)
        self.assertIn("by: 1.1.2", text)
        self.assertIn("(tester)", text)

    def test_the_whole_chat_up_to_the_reply_and_a_note_on_later_focus(self):
        chat = chat_with("one", "first", "two", "second", "three", "third")
        f = flags.flag(chat, 4, "levi", directory=self.dir)
        text = flags.entry(f)
        for kept in ("one", "first", "two", "second"):
            self.assertIn(f"\n{kept}\n", text)
        self.assertNotIn("third", text)
        self.assertIn("2 messages came after it", text)
        self.assertIn("from the later messages", text)

    def test_empty_lists(self):
        flags.write_summaries(self.dir)
        self.assertIn("Nothing flagged.", self.read(flags.OPEN_FILE))
        self.assertIn("Nothing handled yet.", self.read(flags.HANDLED_FILE))

    def test_focus_lines(self):
        chat = ChatState.new()
        self.assertEqual(flags.focus_lines({}), ["(nothing)"])
        chat.focus.recipe = RecipeRef("1", "Book", "Pie")
        chat.focus.numbered = Numbered("match", [RecipeRef("1", "Book", "Pie"),
                                                 RecipeRef("2", "Book", "Tart", gone=True)])
        chat.focus.have = ["pecans", "eggs"]
        chat.focus.scale = ScaleUsed(2.0, "large")
        chat.focus.pending = Pending("pick_batch", "scale", "double it", ["small", "large"])
        from dataclasses import asdict
        lines = flags.focus_lines(asdict(chat.focus))
        self.assertEqual(lines, [
            "recipe: Pie (Book)",
            "numbered (match): 1. Pie (Book); 2. Tart (Book) [gone]",
            "have: pecans, eggs",
            "scale: 2x, batch 'large'",
            "pending: pick_batch for scale, request 'double it', options small, large",
        ])


class ToolTest(FlagCase):
    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tool.main(list(argv), self.dir)
        return out.getvalue()

    def test_counts_and_files(self):
        flags.flag(chat_with("hi", "Hello."), 2, "levi", directory=self.dir)
        out = self.run_tool()
        self.assertIn("1 open, 0 handled.", out)
        self.assertTrue(os.path.exists(os.path.join(self.dir, flags.OPEN_FILE)))

    def test_handled_then_reopen(self):
        f = flags.flag(chat_with("hi", "Hello."), 2, "levi", directory=self.dir)
        self.assertIn("0 open, 1 handled.", self.run_tool("handled", f.id, "1.1.2"))
        self.assertIn("1.1.2", flags.load(f.id, self.dir).handled_by)
        self.assertIn("1 open, 0 handled.", self.run_tool("reopen", f.id))

    def test_an_unknown_id_stops_with_why(self):
        with self.assertRaises(SystemExit) as stopped:
            self.run_tool("handled", "nope1", "1.1.2")
        self.assertIn("no flag", str(stopped.exception.code))

    def test_unreadable_files_are_named(self):
        with open(os.path.join(self.dir, "bad01.json"), "w") as f:
            f.write("{")
        self.assertIn("Couldn't read bad01.json", self.run_tool())


if __name__ == "__main__":
    unittest.main()
