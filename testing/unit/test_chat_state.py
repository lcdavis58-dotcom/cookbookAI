"""
Tests for what a chat remembers (chat/state.py) and saving it
(chat/store.py). Results are built by hand; nothing needs the database
or a model.

Run from app/:
    python3 -m unittest discover testing
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from actions.ask import AskResult  # noqa: E402
from actions.match import SHOW_PER_SECTION, MatchResult  # noqa: E402
from actions.scale import ScaleResult  # noqa: E402
from chat import store  # noqa: E402
from chat.state import (ChatState, Numbered, Pending, RecipeRef, ScaleUsed,  # noqa: E402
                        refresh, remember, resolve, short_title)
from query_utils.title_lookup import Candidate  # noqa: E402


def cand(title, book="Book A", key=None):
    return Candidate(key or f"{book}-{title}", book, title, [([title.lower()], [])], {})


def entry(title, book="Book A"):
    return {"recipe_id": f"{book}-{title}", "book": book, "title": title}


def matched(title):
    return {"entry": entry(title)}


class RememberTest(unittest.TestCase):
    def setUp(self):
        self.state = ChatState.new()
        self.focus = self.state.focus

    def test_ask_recipe(self):
        self.focus.pending = Pending("pick_recipe", "ask", "old")
        remember(self.state, "ask", "recipe for curd", AskResult("recipe", "q", recipe=cand("Curd")))
        self.assertEqual(self.focus.recipe, RecipeRef("Book A-Curd", "Book A", "Curd"))
        self.assertIsNone(self.focus.pending)

    def test_choices_wait_for_a_pick(self):
        result = ScaleResult("choices", choices=[cand("Whipped Cream"), cand("Classic Whipped Cream")])
        remember(self.state, "scale", "double the whipped cream", result)
        self.assertEqual(self.focus.numbered.source, "scale")
        self.assertEqual([r.title for r in self.focus.numbered.items], ["Whipped Cream", "Classic Whipped Cream"])
        self.assertEqual(self.focus.pending, Pending("pick_recipe", "scale", "double the whipped cream"))

    def test_scaled(self):
        result = ScaleResult("scaled", recipe=cand("Topping"), factor=2.0, batch="Full Batch")
        remember(self.state, "scale", "double the topping", result)
        self.assertEqual(self.focus.recipe.title, "Topping")
        self.assertEqual(self.focus.scale, ScaleUsed(2.0, "Full Batch"))

    def test_a_different_recipe_clears_the_scale(self):
        remember(self.state, "scale", "double the topping",
                 ScaleResult("scaled", recipe=cand("Topping"), factor=2.0))
        remember(self.state, "ask", "recipe for topping", AskResult("recipe", "q", recipe=cand("Topping")))
        self.assertEqual(self.focus.scale, ScaleUsed(2.0))
        remember(self.state, "ask", "recipe for curd", AskResult("recipe", "q", recipe=cand("Curd")))
        self.assertIsNone(self.focus.scale)

    def test_pick_batch(self):
        result = ScaleResult("pick_batch", recipe=cand("Topping"), batches=[("Small", None), ("Large", "big")])
        remember(self.state, "scale", "double the topping", result)
        self.assertEqual(self.focus.recipe.title, "Topping")
        self.assertEqual(self.focus.pending, Pending("pick_batch", "scale", "double the topping", ["Small", "Large"]))

    def test_found_but_not_scaled_still_sets_the_recipe(self):
        remember(self.state, "scale", "scale it oddly", ScaleResult("no_factor", recipe=cand("Topping")))
        self.assertEqual(self.focus.recipe.title, "Topping")

    def test_match(self):
        result = MatchResult("matches", have=["lemon", "pecan"],
                             ready=[matched(f"R{i}") for i in range(SHOW_PER_SECTION + 3)],
                             from_scratch=[matched("S")], missing_some=[matched("M")])
        remember(self.state, "match", "lemons, pecans", result)
        self.assertEqual(self.focus.have, ["lemon", "pecan"])
        titles = [r.title for r in self.focus.numbered.items]
        # Numbered as shown: the long section cut at SHOW_PER_SECTION.
        self.assertEqual(len(titles), SHOW_PER_SECTION + 2)
        self.assertEqual(titles[-2:], ["S", "M"])

    def test_a_miss_keeps_the_focus(self):
        remember(self.state, "ask", "recipe for curd", AskResult("recipe", "q", recipe=cand("Curd")))
        self.focus.pending = Pending("pick_batch", "scale", "double it", ["Small"])
        before = json.dumps(self.state.to_dict()["focus"])
        remember(self.state, "scale", "double the zzz", ScaleResult("not_found", reason="no_recipe"))
        remember(self.state, "ask", "zzz", AskResult("nothing", "zzz"))
        remember(self.state, "match", ",", MatchResult("no_ingredients"))
        self.assertEqual(json.dumps(self.state.to_dict()["focus"]), before)


class MessagesTest(unittest.TestCase):
    def test_title_and_unanswered(self):
        state = ChatState.new()
        state.add_user("what can I make with lemons and pecans and a lot of other things I have around")
        self.assertTrue(state.title.endswith("..."))
        self.assertLessEqual(len(state.title), 63)
        self.assertEqual(state.unanswered(), state.messages[0].text)
        state.add_reply("Lots.", "match")
        self.assertIsNone(state.unanswered())
        state.add_user("thanks")
        self.assertTrue(state.title.startswith("what can I make"))

    def test_short_title(self):
        self.assertEqual(short_title("  double   it "), "double it")


class RefreshTest(unittest.TestCase):
    def state_with(self, *refs):
        state = ChatState.new()
        state.focus.recipe = refs[0]
        state.focus.numbered = Numbered("ask", list(refs))
        return state

    def test_same_id(self):
        ref = RecipeRef("Book A-r1", "Book A", "Curd")
        self.assertEqual(resolve(ref, [cand("Curd", key="Book A-r1")]).key, "Book A-r1")

    def test_renumbered_is_found_by_book_and_title(self):
        state = self.state_with(RecipeRef("Book A-r1", "Book A", "Curd"))
        gone = refresh(state, [cand("Tart", key="Book A-r1"), cand("Curd", key="Book A-r7")])
        self.assertEqual(gone, [])
        self.assertEqual(state.focus.recipe.recipe_id, "Book A-r7")

    def test_gone_recipe(self):
        state = self.state_with(RecipeRef("Book A-r1", "Book A", "Curd"), RecipeRef("Book A-r2", "Book A", "Tart"))
        state.focus.pending = Pending("pick_batch", "scale", "double it", ["Small"])
        gone = refresh(state, [cand("Tart", key="Book A-r2")])
        self.assertEqual(gone, ["Curd"])
        self.assertIsNone(state.focus.recipe)
        self.assertIsNone(state.focus.pending)
        # Still in the numbered list, so "the second one" is still Tart.
        self.assertEqual([(r.title, r.gone) for r in state.focus.numbered.items], [("Curd", True), ("Tart", False)])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def full_state(self):
        state = ChatState.new()
        state.add_user("double the topping")
        remember(state, "scale", "double the topping",
                 ScaleResult("pick_batch", recipe=cand("Topping"), batches=[("Small", None)]))
        remember(state, "match", "lemons", MatchResult("matches", have=["lemon"], ready=[matched("Curd")]))
        state.focus.scale = ScaleUsed(0.5, "Small")
        state.add_reply("Which batch size?", "scale")
        return state

    def test_round_trip(self):
        state = self.full_state()
        store.save(state, self.dir)
        self.assertEqual(store.load(state.id, self.dir), state)
        self.assertEqual(os.listdir(self.dir), [f"{state.id}.json"])

    def test_list_and_latest(self):
        old, new = ChatState.new(), ChatState.new()
        old.add_user("first")
        old.updated, new.updated = "2026-01-01T10:00:00", "2026-02-01T10:00:00"
        new.title = "second"
        for s in (old, new):
            store.save(s, self.dir)
        with open(os.path.join(self.dir, "broken.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(self.dir, "future.json"), "w") as f:
            json.dump({"format": 99, "id": "future"}, f)
        chats = store.list_chats(self.dir)
        self.assertEqual([c.id for c in chats], [new.id, old.id, "broken", "future"])
        self.assertIsNone(chats[0].error)
        self.assertIn("can't be read", chats[2].error)
        self.assertIn("format 99", chats[3].error)
        self.assertEqual(store.latest(self.dir).id, new.id)
        with self.assertRaises(store.ChatFileError):
            store.load("broken", self.dir)
        with self.assertRaises(store.ChatFileError):
            store.load("nothing-here", self.dir)

    def test_failed_save_keeps_the_last_version(self):
        state = self.full_state()
        store.save(state, self.dir)
        state.add_user("one more")
        with mock.patch.object(store.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.save(state, self.dir)
        self.assertEqual(len(store.load(state.id, self.dir).messages), 2)

    def test_no_folder_yet(self):
        self.assertEqual(store.list_chats(os.path.join(self.dir, "missing")), [])
        self.assertIsNone(store.latest(os.path.join(self.dir, "missing")))


if __name__ == "__main__":
    unittest.main()
