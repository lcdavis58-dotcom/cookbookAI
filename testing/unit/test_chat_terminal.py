"""
Tests for the terminal chat (chat/terminal.py), driven with scripted
input. Messages are ones the routing rules answer, so no model is
needed; where a model call would happen, it's patched to fail or stop.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import shutil
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from testing.unit.test_chat_router import CANDIDATES, ref  # noqa: F401  (also stubs chromadb/ollama)

from actions.ask import AskResult  # noqa: E402
from actions.match import MatchResult  # noqa: E402
from actions.scale import ScaleResult  # noqa: E402
from chat import flags, store, turn  # noqa: E402
from chat.state import ChatState, Numbered, Pending  # noqa: E402
from chat.terminal import Terminal, when  # noqa: E402

NEED_RECIPE = "Which recipe should I scale?"


class Script:
    """Answers each read() from a list; EOFError once it runs out."""

    def __init__(self, lines):
        self.lines = list(lines)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class TerminalTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.flags = tempfile.mkdtemp()
        self.out = []

    def tearDown(self):
        shutil.rmtree(self.dir)
        shutil.rmtree(self.flags)

    def run_terminal(self, lines, **options):
        """Run the terminal on scripted lines. Actions don't run (they'd
        need the database): each route is recorded in self.routes and
        answered with a "nothing found" result."""
        script = Script(lines)
        self.routes = []

        def fake_run(router, route):
            self.routes.append(route.label)
            return {"ask": AskResult("nothing", route.request),
                    "scale": ScaleResult("not_found", reason="no_recipe"),
                    "match": MatchResult("no_ingredients")}[route.action]

        term = Terminal(read=script, write=self.out.append, directory=self.dir, candidates=CANDIDATES,
                        flags_dir=self.flags)
        with mock.patch.object(turn, "run_route", side_effect=fake_run):
            term.run(**options)
        return term, script

    def text(self):
        return "\n".join(self.out)

    def saved(self, title="halve it", messages=("halve it",), reply=True, updated=None):
        state = ChatState.new()
        for m in messages:
            state.add_user(m)
            if reply:
                state.add_reply(NEED_RECIPE, None, "rule: reply need recipe")
                state.focus.pending = Pending("need_recipe", "scale", m)
        state.title = title
        if updated:
            state.updated = updated
        store.save(state, self.dir)
        return state

    def test_new_chat_when_none_saved(self):
        term, script = self.run_terminal(["halve it", "/quit"])
        self.assertIn("--- New chat ---", self.text())
        self.assertIn(NEED_RECIPE, self.text())
        self.assertTrue(self.text().endswith("Chat saved."))
        [summary] = store.list_chats(self.dir)
        self.assertEqual(summary.message_count, 2)
        self.assertNotIn("Continue", " ".join(script.prompts))

    def test_continue_the_latest(self):
        old = self.saved()
        term, script = self.run_terminal(["", "the lemon curd"])
        self.assertIn('Continue "halve it"', script.prompts[0])
        self.assertEqual(term.state.id, old.id)
        # The pending "halve it" is finished by naming a recipe (scaling
        # itself is patched out: it would need the recipe's text).
        self.assertEqual(self.routes[-1], "pending: scale named")
        self.assertIn("You: halve it", self.text())

    def test_decline_to_continue(self):
        old = self.saved()
        term, _ = self.run_terminal(["n", "halve it"])
        self.assertNotEqual(term.state.id, old.id)
        self.assertEqual(len(store.list_chats(self.dir)), 2)

    def test_unanswered_message_is_offered_again(self):
        old = self.saved(messages=["halve it"], reply=False)
        term, script = self.run_terminal(["y", "y"])
        self.assertIn("didn't get an answer", script.prompts[1])
        self.assertIn(NEED_RECIPE, self.text())
        loaded = store.load(old.id, self.dir)
        self.assertEqual([t.role for t in loaded.messages], ["user", "assistant"])

    def test_list_open_and_new(self):
        first = self.saved(title="first", updated="2026-01-01T10:00:00")
        self.saved(title="second", updated="2026-02-01T10:00:00")
        term, _ = self.run_terminal(["n", "/list", "/open 2", "/new", "/quit"])
        text = self.text()
        self.assertIn("1. second", text)
        self.assertIn("2. first", text)
        self.assertIn('--- "first"', text)
        self.assertIn("--- New chat ---", text.split('--- "first"')[1])
        self.assertNotEqual(term.state.id, first.id)

    def test_open_by_flag(self):
        old = self.saved(title="mine")
        term, script = self.run_terminal([], open_ref=old.id)
        self.assertEqual(term.state.id, old.id)
        self.assertNotIn("Continue", " ".join(script.prompts))
        term, _ = self.run_terminal([], open_ref="99")
        self.assertIn("Couldn't open chat 99", self.text())

    def test_gone_recipes_are_named(self):
        old = self.saved()
        old.focus.numbered = Numbered("ask", [ref("Lemon Curd")])
        old.focus.numbered.items[0].title = "Old Curd"
        store.save(old, self.dir)
        self.run_terminal(["y"])
        self.assertIn("Not in the books anymore, they were re-ingested: Old Curd", self.text())

    def test_errors_leave_the_message_unanswered(self):
        for error, expected in [(ConnectionError("refused"), "Is Ollama running?"),
                                (KeyboardInterrupt(), "Stopped."),
                                (ValueError("odd"), "Something went wrong (ValueError: odd)")]:
            with self.subTest(error=type(error).__name__):
                self.out.clear()
                with mock.patch.object(turn, "respond", side_effect=error):
                    term, _ = self.run_terminal(["/new", "anything at all"], new=True)
                self.assertIn(expected, self.text())
                self.assertEqual(term.state.unanswered(), "anything at all")
                self.assertTrue(self.text().endswith("Chat saved."))

    def test_flag_the_last_reply(self):
        term, _ = self.run_terminal(["halve it", "/flag", "/flag"], new=True)
        [f] = flags.all_flags(self.flags)[0]
        self.assertEqual((f.account, f.chat_id, f.message, f.note), (flags.TERMINAL, term.state.id, 2, ""))
        self.assertEqual(f.reply["text"], NEED_RECIPE)
        self.assertIn(f"Flagged the last reply as wrong ({f.id})", self.text())
        self.assertIn("The last reply is already flagged.", self.text())

    def test_nothing_to_flag_yet(self):
        self.run_terminal(["/flag", "/unflag"], new=True)
        self.assertIn("There's no reply to flag yet.", self.text())
        self.assertIn("The last reply isn't flagged.", self.text())
        self.assertEqual(flags.all_flags(self.flags), ([], []))

    def test_unflag(self):
        self.run_terminal(["halve it", "/flag", "/unflag", "/unflag"], new=True)
        self.assertIn("Took the flag off the last reply.", self.text())
        self.assertIn("The last reply isn't flagged.", self.text())
        self.assertEqual(flags.all_flags(self.flags), ([], []))

    def test_a_handled_flag_stays(self):
        old = self.saved()
        f = flags.flag(old, 2, flags.TERMINAL, directory=self.flags)
        flags.mark_handled(f.id, "1.1.2", self.flags)
        self.run_terminal(["y", "/unflag"])
        self.assertIn("already handled, so it stays", self.text())
        self.assertEqual(len(flags.all_flags(self.flags)[0]), 1)

    def test_help_lists_flag(self):
        self.run_terminal(["/help"], new=True)
        self.assertIn("/flag", self.text())

    def test_unknown_command(self):
        self.run_terminal(["/bake"], new=True)
        self.assertIn("Unknown command /bake", self.text())

    def test_when(self):
        now = datetime(2026, 11, 6, 21, 30)
        self.assertEqual(when("2026-11-06T21:29:50", now), "just now")
        self.assertEqual(when("2026-11-06T21:10:00", now), "20 minutes ago")
        self.assertEqual(when("2026-11-06T09:05:00", now), "today 9:05 AM")
        self.assertEqual(when("2026-11-05T21:32:00", now), "yesterday 9:32 PM")
        self.assertEqual(when("2026-10-30T21:32:00", now), "Oct 30")
        self.assertEqual(when("", now), "at an unknown time")


if __name__ == "__main__":
    unittest.main()
