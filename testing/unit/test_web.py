"""
Tests for the website (web/), using Flask's test client on a temporary
chats folder. Nothing here needs the database or a model.

Run from app/:
    python3 -m unittest discover testing
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from testing.unit.test_chat_router import CANDIDATES  # (also stubs chromadb/ollama)

from chat import store  # noqa: E402
from chat.state import ChatState, RecipeRef  # noqa: E402
from web import create_app  # noqa: E402


class WebTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = mock.patch("web.routes.load_candidates", return_value=CANDIDATES)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = create_app(self.dir).test_client()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def saved_chat(self, text="double the whipped cream", reply="Scaling it.", chat_id=None):
        chat = ChatState.new()
        if chat_id:
            chat.id = chat_id
        chat.add_user(text)
        if reply:
            chat.add_reply(reply)
        store.save(chat, self.dir)
        return chat

    def page(self, url):
        return self.client.get(url).get_data(as_text=True)

    def test_no_chats_yet(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No saved chats yet", response.get_data(as_text=True))

    def test_home_opens_the_latest_chat(self):
        older = self.saved_chat(chat_id="2026-11-01-0900-aaaa")
        newer = self.saved_chat(chat_id="2026-11-02-0900-bbbb")
        older.updated, newer.updated = "2026-11-01T09:00:00", "2026-11-02T09:00:00"
        store.save(older, self.dir)
        store.save(newer, self.dir)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith(f"/chats/{newer.id}"))

    def test_shows_the_conversation_and_the_list(self):
        chat = self.saved_chat()
        page = self.page(f"/chats/{chat.id}")
        self.assertIn("Scaling it.", page)
        self.assertIn(f'href="/chats/{chat.id}"', page)

    def test_message_text_is_escaped(self):
        chat = self.saved_chat(text="<script>alert(1)</script>", reply="<b>hi</b>")
        page = self.page(f"/chats/{chat.id}")
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<b>hi", page)
        self.assertIn("&lt;script&gt;", page)

    def test_badly_formed_ids_never_reach_the_files(self):
        with mock.patch("web.routes.store.load") as load:
            for chat_id in ("nope", "..%5C..%5Csecret", "..%2F..%2Fsecret", "2026-11-01-0900-AAAA",
                            "2026-11-01-0900-aaaa.json", "2026-11-01-0900-aaaa%5C"):
                with self.subTest(chat_id):
                    self.assertEqual(self.client.get(f"/chats/{chat_id}").status_code, 404)
            load.assert_not_called()

    def test_missing_chat_is_not_found(self):
        self.assertEqual(self.client.get("/chats/2026-11-01-0900-aaaa").status_code, 404)

    def test_unreadable_chat_is_counted_not_linked(self):
        with open(os.path.join(self.dir, "2026-11-01-0900-aaaa.json"), "w", encoding="utf-8") as f:
            f.write("not json")
        self.assertEqual(self.client.get("/chats/2026-11-01-0900-aaaa").status_code, 404)
        page = self.page("/")
        self.assertIn("1 saved chat couldn't be read", page)
        self.assertNotIn('href="/chats/2026-11-01-0900-aaaa"', page)

    def test_file_with_another_name_is_not_listed(self):
        chat = self.saved_chat(chat_id="handmade")
        self.assertNotIn(chat.title, self.page("/"))

    def test_unanswered_message_is_noted(self):
        chat = self.saved_chat(reply=None)
        self.assertIn("didn't get an answer", self.page(f"/chats/{chat.id}"))

    def test_viewing_does_not_save(self):
        chat = self.saved_chat()
        chat.focus.recipe = RecipeRef("gone-1", "Book A", "No Longer In The Book")
        store.save(chat, self.dir)
        path = os.path.join(self.dir, f"{chat.id}.json")
        with open(path, encoding="utf-8") as f:
            before = json.load(f)
        page = self.page(f"/chats/{chat.id}")
        self.assertIn("No Longer In The Book", page)
        self.assertIn("Not in the books anymore", page)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), before)


if __name__ == "__main__":
    unittest.main()
