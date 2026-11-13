"""
Tests for the website (web/), using Flask's test client on temporary
folders. Nothing here needs the database or a model.

Run from app/:
    python3 -m unittest discover testing
"""

import html
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from testing.unit.test_chat_router import CANDIDATES  # (also stubs chromadb/ollama)

from chat import store  # noqa: E402
from chat.state import ChatState, Numbered, Pending, RecipeRef  # noqa: E402
from common import accounts, models  # noqa: E402
from common.config import MODEL_TIMEOUT  # noqa: E402
from match_utils.matching import parse_have  # noqa: E402
from web import create_app  # noqa: E402
from web.auth import FAILURE_LIMIT, WAIT_SECONDS, Throttle  # noqa: E402
from web.routes import MAX_MESSAGE_CHARS, MAX_TITLE_CHARS  # noqa: E402

PASSWORD = "correct horse"


class WebCase(unittest.TestCase):
    https = False
    config = {"WTF_CSRF_ENABLED": False}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.chats = os.path.join(self.root, "chats")
        self.users = os.path.join(self.root, "users.json")
        patcher = mock.patch("web.routes.load_candidates", return_value=CANDIDATES)
        patcher.start()
        self.addCleanup(patcher.stop)
        accounts.set_password("levi", PASSWORD, self.users)
        self.app = create_app(self.chats, self.users, os.path.join(self.root, "secret.key"),
                              https=self.https, config=self.config)
        self.client = self.app.test_client()

    def sign_in(self, client=None, name="levi", password=PASSWORD):
        return (client or self.client).post("/login", data={"username": name, "password": password})

    def user_dir(self, name="levi"):
        return os.path.join(self.chats, "users", name)

    def saved_chat(self, text="double the whipped cream", reply="Scaling it.", chat_id=None, user="levi"):
        chat = ChatState.new()
        if chat_id:
            chat.id = chat_id
        chat.add_user(text)
        if reply:
            chat.add_reply(reply)
        store.save(chat, self.user_dir(user))
        return chat

    def page(self, url):
        return self.client.get(url).get_data(as_text=True)


class ViewingTest(WebCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.dir = self.user_dir()

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

    def test_stylesheet_and_scripts_are_linked_and_served(self):
        page = self.page("/")
        for link, url in (("href", "/static/style.css"), ("src", "/static/htmx.min.js"), ("src", "/static/app.js")):
            with self.subTest(url):
                self.assertIn(f'{link}="{url}"', page)
                with self.client.get(url) as response:
                    self.assertEqual(response.status_code, 200)

    def test_page_has_what_the_message_box_script_needs(self):
        page = self.page("/")
        for element in ('id="message"', 'id="send"', 'id="composer"', 'id="send-error"'):
            self.assertIn(element, page)

    def test_missing_chat_is_not_found(self):
        self.assertEqual(self.client.get("/chats/2026-11-01-0900-aaaa").status_code, 404)

    def test_unreadable_chat_is_counted_not_linked(self):
        os.makedirs(self.dir)
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
        self.assertIn("didn't get an answer", html.unescape(self.page(f"/chats/{chat.id}")))

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


class SendingTest(WebCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.dir = self.user_dir()
        self.answers = self.app.extensions["answers"]
        self.release = threading.Event()
        self.release.set()
        self.failure = None
        self.answers.work = self.fake_work

    def fake_work(self, directory, chat_id):
        self.release.wait(5)
        if self.failure:
            raise self.failure
        chat = store.load(chat_id, directory)
        chat.add_reply(f"Reply to: {chat.unanswered()}")
        store.save(chat, directory)

    def hold(self):
        """Keep the next reply in progress until the test is done with it."""
        self.release.clear()
        self.addCleanup(self.answers.join)
        self.addCleanup(self.release.set)

    def send(self, chat, text="how long does it chill?"):
        return self.client.post(f"/chats/{chat.id}/messages", data={"message": text},
                                headers={"HX-Trigger": "composer"})

    def after_match(self, have=("pecan", "half and half")):
        chat = self.saved_chat(reply=None)
        chat.add_reply("You have: ...", action="match")
        chat.focus.have = list(have)
        chat.focus.numbered = Numbered("match", [RecipeRef("a-1", "Book A", "Pie <One>"),
                                                 RecipeRef("a-2", "Book A", "It's Pie Two")])
        store.save(chat, self.dir)
        return chat

    def test_match_results_get_numbers_and_ingredient_tags(self):
        page = self.page(f"/chats/{self.after_match().id}")
        self.assertRegex(page, r"""hx-vals='\{"message": "1"\}'""")
        self.assertRegex(page, r"""hx-vals='\{"message": "2"\}'""")
        self.assertIn("without half and half", page)
        self.assertIn('aria-label="Remove pecan"', page)
        self.assertIn('name="add"', page)
        self.assertIn("Pie &lt;One&gt;", page)

    def test_tapped_text_cannot_break_out_of_its_attribute(self):
        chat = self.after_match(have=["it's <b>"])
        page = self.page(f"/chats/{chat.id}")
        self.assertNotIn("<b> ✕", page)
        tapped = json.loads(re.search(r"hx-vals='(\{[^']*without[^']*\})'", page).group(1))
        self.assertEqual(tapped["message"], "without it's <b>")

    def test_which_one_list_gets_numbers_only(self):
        chat = self.after_match()
        chat.focus.pending = Pending("pick_recipe", "scale", "double the pie")
        store.save(chat, self.dir)
        page = self.page(f"/chats/{chat.id}")
        self.assertRegex(page, r"""hx-vals='\{"message": "1"\}'""")
        self.assertNotIn("without", page)

    def test_batch_question_gets_batch_buttons(self):
        chat = self.saved_chat()
        chat.focus.pending = Pending("pick_batch", "scale", "double it", ["Full Batch", "Half Batch"])
        store.save(chat, self.dir)
        page = self.page(f"/chats/{chat.id}")
        self.assertRegex(page, r"""hx-vals='\{"message": "Half Batch"\}'""")

    def test_old_results_are_not_tappable_after_moving_on(self):
        chat = self.after_match()
        chat.add_user("how long does it chill?")
        chat.add_reply("About an hour.", action="ask")
        store.save(chat, self.dir)
        self.assertNotIn('hx-vals=\'{"message"', self.page(f"/chats/{chat.id}"))

    def test_nothing_tappable_while_working(self):
        chat = self.after_match()
        self.hold()
        self.send(chat)
        self.assertNotIn("hx-vals", self.client.get(f"/chats/{chat.id}/status").get_data(as_text=True))

    def test_finished_reply_includes_its_buttons(self):
        chat = self.after_match()
        self.answers.work = lambda directory, chat_id: self._reply_match(directory, chat_id)
        self.send(chat, "add butter")
        self.answers.join()
        self.assertIn("without pecan", self.client.get(f"/chats/{chat.id}/status").get_data(as_text=True))

    def _reply_match(self, directory, chat_id):
        chat = store.load(chat_id, directory)
        chat.add_reply("You have: ...", action="match")
        store.save(chat, directory)

    def test_tap_sends_the_message_and_leaves_the_box_alone(self):
        chat = self.after_match()
        self.hold()
        body = self.client.post(f"/chats/{chat.id}/messages", data={"message": "1"}).get_data(as_text=True)
        self.assertEqual(self.saved(chat).unanswered(), "1")
        self.assertNotIn("<textarea", body)

    def test_add_box_sends_add(self):
        chat = self.after_match()
        self.hold()
        self.client.post(f"/chats/{chat.id}/messages", data={"add": " butter "},
                         headers={"HX-Trigger": "add-ingredient"})
        self.assertEqual(self.saved(chat).unanswered(), "add butter")

    def saved(self, chat):
        return store.load(chat.id, self.dir)

    def test_first_message_makes_a_chat_and_opens_it(self):
        response = self.client.post("/chats", data={"message": "double the cream"})
        self.answers.join()
        chats = store.list_chats(self.dir)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["HX-Redirect"], f"/chats/{chats[0].id}")
        self.assertEqual(chats[0].title, "double the cream")
        self.assertEqual(chats[0].message_count, 2)

    def test_send_returns_her_message_and_thinking(self):
        chat = self.saved_chat()
        self.hold()
        body = self.send(chat, "<i>how long</i>").get_data(as_text=True)
        self.assertIn("&lt;i&gt;how long", body)
        self.assertIn('hx-trigger="every 2s"', body)
        self.assertIn('id="m3"', body)
        self.assertIn("Thinking", body)
        self.assertRegex(body, r'<textarea[^>]*hx-swap-oob')
        self.assertRegex(body, r'<button id="send"[^>]*hx-swap-oob="true"\s+disabled')

    def test_her_message_is_saved_before_the_reply(self):
        chat = self.saved_chat()
        self.hold()
        self.send(chat, "still here?")
        self.assertEqual(self.saved(chat).unanswered(), "still here?")

    def test_status_while_working_has_no_reply_and_keeps_checking(self):
        chat = self.saved_chat()
        self.hold()
        self.send(chat)
        body = self.client.get(f"/chats/{chat.id}/status").get_data(as_text=True)
        self.assertIn("Thinking", body)
        self.assertNotIn("<article", body)

    def test_status_says_when_it_is_slow(self):
        chat = self.saved_chat()
        self.hold()
        self.send(chat)
        with mock.patch("web.routes.SLOW_AFTER_SECONDS", -1):
            self.assertIn("Still working", self.client.get(f"/chats/{chat.id}/status").get_data(as_text=True))

    def test_finished_status_delivers_the_reply_once_and_stops_checking(self):
        chat = self.saved_chat()
        self.send(chat)
        self.answers.join()
        response = self.client.get(f"/chats/{chat.id}/status")
        body = response.get_data(as_text=True)
        self.assertIn("Reply to: how long does it chill?", body)
        self.assertNotIn("every 2s", body)
        self.assertEqual(response.headers["HX-Reswap"], "outerHTML show:#m4:top")
        self.assertRegex(body, r'<button id="send"[^>]*hx-swap-oob="true"\s*>')

    def test_a_second_message_waits_for_the_reply(self):
        chat = self.saved_chat()
        self.hold()
        self.send(chat, "first")
        body = self.send(chat, "second").get_data(as_text=True)
        self.assertNotIn("second", body)
        self.assertNotRegex(body, r"<textarea")     # what she typed stays in the box
        self.assertEqual(self.saved(chat).unanswered(), "first")

    def test_reloading_while_working_keeps_checking(self):
        chat = self.saved_chat()
        self.hold()
        self.send(chat)
        page = self.page(f"/chats/{chat.id}")
        self.assertIn("every 2s", page)
        self.assertNotIn("Answer it now", page)
        self.assertRegex(page, r'<button id="send"[^>]*\s+disabled')

    def test_page_offers_to_answer_after_a_restart(self):
        chat = self.saved_chat(reply=None)
        page = self.page(f"/chats/{chat.id}")
        self.assertIn("Answer it now", page)
        self.assertNotIn("every 2s", page)

    def test_answer_button_answers(self):
        chat = self.saved_chat(reply=None)
        self.hold()
        body = self.client.post(f"/chats/{chat.id}/answer").get_data(as_text=True)
        self.assertIn("every 2s", body)
        self.release.set()
        self.answers.join()
        self.assertIsNone(self.saved(chat).unanswered())
        self.assertEqual(len(self.saved(chat).messages), 2)

    def test_answer_button_on_an_answered_chat_shows_the_reply(self):
        chat = self.saved_chat()
        with mock.patch.object(self.answers, "submit") as submit:
            body = self.client.post(f"/chats/{chat.id}/answer").get_data(as_text=True)
        submit.assert_not_called()
        self.assertIn("Scaling it.", body)

    def test_failures_keep_the_message_and_offer_to_retry(self):
        for error, text in ((ConnectionError("down"), "couldn't reach the model"),
                            (TimeoutError("slow"), "took too long"),
                            (ValueError("secret detail"), "Something went wrong")):
            with self.subTest(text):
                self.failure = error
                chat = self.saved_chat(reply=None, chat_id=f"2026-11-01-0900-{len(text) % 10}abc")
                self.client.post(f"/chats/{chat.id}/answer")
                self.answers.join()
                body = self.client.get(f"/chats/{chat.id}/status").get_data(as_text=True)
                self.assertIn(text, html.unescape(body))
                self.assertIn("Answer it now", body)
                self.assertNotIn("secret detail", body)
                self.assertIsNotNone(self.saved(chat).unanswered())

    def test_retry_clears_the_failure(self):
        chat = self.saved_chat(reply=None)
        self.failure = ConnectionError("down")
        self.client.post(f"/chats/{chat.id}/answer")
        self.answers.join()
        self.failure = None
        self.client.post(f"/chats/{chat.id}/answer")
        self.answers.join()
        self.assertIn("Reply to", self.client.get(f"/chats/{chat.id}/status").get_data(as_text=True))

    def test_blank_or_huge_messages_are_refused(self):
        chat = self.saved_chat()
        for text in ("", "   \n ", "x" * (MAX_MESSAGE_CHARS + 1)):
            with self.subTest(len(text)):
                self.assertEqual(self.send(chat, text).status_code, 400)
        self.assertEqual(len(self.saved(chat).messages), 2)

    def test_another_accounts_chat_cannot_be_used(self):
        accounts.set_password("tester", PASSWORD, self.users)
        hers = self.saved_chat(text="private")
        other = self.app.test_client()
        self.sign_in(other, "tester")
        for response in (other.post(f"/chats/{hers.id}/messages", data={"message": "hi"}),
                         other.post(f"/chats/{hers.id}/answer"),
                         other.get(f"/chats/{hers.id}/status")):
            self.assertEqual(response.status_code, 404)
        self.assertEqual(len(self.saved(hers).messages), 2)

    def test_signed_out_htmx_request_goes_to_the_sign_in_page(self):
        chat = self.saved_chat()
        self.client.post("/logout")
        response = self.client.get(f"/chats/{chat.id}/status", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["HX-Redirect"], "/login")


class ManagingChatsTest(WebCase):
    def setUp(self):
        super().setUp()
        self.sign_in()
        self.dir = self.user_dir()
        self.answers = self.app.extensions["answers"]
        self.release = threading.Event()
        self.answers.work = lambda *_: self.release.wait(5)

    def rename(self, chat, title="Sunday pies"):
        return self.client.post(f"/chats/{chat.id}/rename", data={"title": title})

    def working_on(self, chat):
        self.addCleanup(self.answers.join)
        self.addCleanup(self.release.set)
        self.client.post(f"/chats/{chat.id}/answer")

    def test_pencil_is_in_the_top_bar_and_x_in_the_list(self):
        chat = self.saved_chat()
        page = self.page(f"/chats/{chat.id}")
        header = page[page.index('class="chat-header"'):page.index("</header>")]
        side = page[page.index('id="chat-list"'):page.index("</nav>")]
        self.assertIn(f'hx-post="/chats/{chat.id}/rename"', header)
        self.assertNotIn("/delete", header)
        self.assertIn(f'hx-post="/chats/{chat.id}/delete"', side)
        self.assertIn("hx-confirm=", side)

    def test_only_the_open_chat_is_marked_open(self):
        first, second = self.saved_chat(chat_id="2026-11-01-0900-aaaa"), self.saved_chat(chat_id="2026-11-02-0900-bbbb")
        page = self.page(f"/chats/{first.id}")
        self.assertEqual(page.count('hx-vals=\'{"open": "1"}\''), 1)
        self.assertIn(f'href="/chats/{second.id}"', page)

    def test_new_chat_page_has_no_pencil(self):
        self.assertNotIn("/rename", self.page("/chats/new"))

    def test_confirm_text_names_the_chat_safely(self):
        chat = self.saved_chat(text='a "quoted" <b> name')
        page = self.page(f"/chats/{chat.id}")
        self.assertNotIn('a "quoted" <b>', page)
        self.assertIn("hx-confirm=\"Delete “a &#34;quoted&#34; &lt;b&gt; name”", page)

    def test_rename(self):
        chat = self.saved_chat()
        response = self.rename(chat, "  Sunday pies ")
        self.assertEqual(response.headers["HX-Redirect"], f"/chats/{chat.id}")
        saved = store.load(chat.id, self.dir)
        self.assertEqual(saved.title, "Sunday pies")
        self.assertEqual(saved.updated, chat.updated)   # doesn't move up the list
        self.assertEqual(len(saved.messages), 2)

    def test_a_renamed_chat_keeps_its_name_after_more_messages(self):
        chat = self.saved_chat()
        self.rename(chat)
        saved = store.load(chat.id, self.dir)
        saved.add_user("another message")
        self.assertEqual(saved.title, "Sunday pies")

    def test_rename_is_escaped(self):
        chat = self.saved_chat()
        self.rename(chat, '"><script>alert(1)</script>')
        self.assertNotIn("<script>alert", self.page(f"/chats/{chat.id}"))

    def test_bad_names_are_refused(self):
        chat = self.saved_chat()
        for title in ("", "   ", "x" * (MAX_TITLE_CHARS + 1)):
            with self.subTest(len(title)):
                self.assertEqual(self.rename(chat, title).status_code, 400)

    def test_deleting_the_open_chat_leaves_it(self):
        chat = self.saved_chat()
        response = self.client.post(f"/chats/{chat.id}/delete", data={"open": "1"})
        self.assertEqual(response.headers["HX-Redirect"], "/")
        self.assertEqual(store.list_chats(self.dir), [])
        self.assertEqual(self.client.get(f"/chats/{chat.id}").status_code, 404)

    def test_deleting_another_chat_only_removes_its_row(self):
        chat = self.saved_chat()
        response = self.client.post(f"/chats/{chat.id}/delete")
        self.assertEqual((response.status_code, response.get_data()), (200, b""))
        self.assertNotIn("HX-Redirect", response.headers)
        self.assertEqual(store.list_chats(self.dir), [])

    def test_both_wait_for_a_reply_in_progress(self):
        chat = self.saved_chat(reply=None)
        self.working_on(chat)
        self.assertEqual(self.rename(chat).status_code, 409)
        self.assertEqual(self.client.post(f"/chats/{chat.id}/delete").status_code, 409)
        self.assertEqual(store.load(chat.id, self.dir).title, chat.title)

    def test_another_accounts_chat_is_untouchable(self):
        accounts.set_password("tester", PASSWORD, self.users)
        hers = self.saved_chat()
        other = self.app.test_client()
        self.sign_in(other, "tester")
        self.assertEqual(other.post(f"/chats/{hers.id}/rename", data={"title": "x"}).status_code, 404)
        self.assertEqual(other.post(f"/chats/{hers.id}/delete").status_code, 404)
        self.assertEqual(store.load(hers.id, self.dir).title, hers.title)

    def test_changes_need_post(self):
        chat = self.saved_chat()
        self.assertEqual(self.client.get(f"/chats/{chat.id}/delete").status_code, 405)


class HalfAndHalfTest(unittest.TestCase):
    def test_it_is_one_ingredient(self):
        for text in ("half and half", "Half And Half", "half-and-half"):
            with self.subTest(text):
                self.assertEqual(parse_have(f"pumpkin, {text}"), ["pumpkin", "half-and-half"])

    def test_other_ands_still_split(self):
        self.assertEqual(parse_have("pecans and lemons"), ["pecan", "lemon"])


class ModelTimeoutTest(unittest.TestCase):
    def test_kinds_of_failure(self):
        timeout = type("ReadTimeout", (Exception,), {})()
        connect = type("ConnectError", (Exception,), {})()
        self.assertTrue(models.is_timeout(timeout))
        self.assertFalse(models.is_connection_error(timeout))
        self.assertTrue(models.is_connection_error(connect))
        self.assertFalse(models.is_timeout(connect))

    def test_calls_have_a_time_limit(self):
        with mock.patch("common.models._client", None), mock.patch("common.models.ollama") as ollama:
            models.chat("test", [])
        ollama.Client.assert_called_once_with(timeout=MODEL_TIMEOUT)


class SecurityHtmxTest(WebCase):
    config = {}

    def test_chat_page_gives_htmx_the_token_and_it_is_accepted(self):
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.page("/login")).group(1)
        self.client.post("/login", data={"username": "levi", "password": PASSWORD, "csrf_token": token})
        chat = self.saved_chat()
        self.app.extensions["answers"].work = lambda *_: None
        self.assertEqual(self.client.post(f"/chats/{chat.id}/messages", data={"message": "hi"}).status_code, 400)
        header = re.search(r"""hx-headers='\{"X-CSRFToken": "([^"]+)"\}'""", self.page(f"/chats/{chat.id}")).group(1)
        response = self.client.post(f"/chats/{chat.id}/messages", data={"message": "hi"},
                                    headers={"X-CSRFToken": header})
        self.assertEqual(response.status_code, 200)
        self.app.extensions["answers"].join()


class SignInTest(WebCase):
    def test_pages_need_a_sign_in(self):
        for url in ("/", "/chats/2026-11-01-0900-aaaa"):
            with self.subTest(url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith("/login"))

    def test_right_password_signs_in_and_out(self):
        self.assertEqual(self.sign_in().status_code, 302)
        self.assertIn("Signed in as levi", self.page("/"))
        self.client.post("/logout")
        self.assertTrue(self.client.get("/").location.endswith("/login"))

    def test_user_name_ignores_case(self):
        self.assertEqual(self.sign_in(name=" LEVI ").status_code, 302)

    def test_wrong_password_and_unknown_name_look_the_same(self):
        def without_token(response):    # the form token has the time in it
            return re.sub(r'value="[^"]+"', "", response.get_data(as_text=True))

        wrong = self.sign_in(password="nope nope")
        unknown = self.sign_in(name="nobody")
        self.assertEqual((wrong.status_code, without_token(wrong)), (401, without_token(unknown)))
        self.assertEqual(unknown.status_code, 401)

    def test_repeated_failures_wait_even_with_the_right_password(self):
        for _ in range(FAILURE_LIMIT):
            self.sign_in(password="nope nope")
        self.assertEqual(self.sign_in().status_code, 401)

    def test_changing_a_password_signs_out_other_devices(self):
        self.sign_in()
        accounts.set_password("levi", "a new password", self.users)
        self.assertTrue(self.client.get("/").location.endswith("/login"))

    def test_removed_account_is_signed_out(self):
        self.sign_in()
        accounts.remove("levi", self.users)
        self.assertTrue(self.client.get("/").location.endswith("/login"))

    def test_accounts_see_only_their_own_chats(self):
        accounts.set_password("tester", PASSWORD, self.users)
        hers = self.saved_chat(text="her private chat")
        self.sign_in(name="tester")
        self.assertEqual(self.client.get(f"/chats/{hers.id}").status_code, 404)
        self.assertNotIn("her private chat", self.page("/"))

    def test_terminal_chats_are_not_on_the_website(self):
        chat = ChatState.new()
        chat.add_user("a terminal chat")
        store.save(chat, self.chats)
        self.sign_in()
        self.assertNotIn("a terminal chat", self.page("/"))
        self.assertEqual([c.title for c in store.list_chats(self.chats)], ["a terminal chat"])


class SecurityTest(WebCase):
    config = {}                     # the real forgery protection

    def token(self, url="/login"):
        return re.search(r'name="csrf_token" value="([^"]+)"', self.page(url)).group(1)

    def test_post_without_a_token_is_refused(self):
        self.assertEqual(self.sign_in().status_code, 400)

    def test_post_with_a_token_works(self):
        response = self.client.post("/login", data={"username": "levi", "password": PASSWORD,
                                                    "csrf_token": self.token()})
        self.assertEqual(response.status_code, 302)

    def test_sign_out_needs_a_token(self):
        self.client.post("/login", data={"username": "levi", "password": PASSWORD, "csrf_token": self.token()})
        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertIn("Signed in as levi", self.page("/"))

    def test_sign_out_by_get_is_refused(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_headers(self):
        headers = self.client.get("/login").headers
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_cookie_settings(self):
        cookie = self.client.get("/login").headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie)

    def test_oversized_request_is_refused(self):
        response = self.client.post("/login", data={"username": "x" * 70000})
        self.assertEqual(response.status_code, 413)

    def test_secret_key_survives_a_restart(self):
        path = os.path.join(self.root, "secret.key")
        self.assertEqual(create_app(self.chats, self.users, path).secret_key, self.app.secret_key)


class HttpsTest(WebCase):
    https = True

    def test_cookie_is_https_only(self):
        self.assertIn("Secure", self.sign_in().headers["Set-Cookie"])


class ThrottleTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.throttle = Throttle(clock=lambda: self.now)

    def fail_login(self, times=FAILURE_LIMIT, name="levi"):
        for _ in range(times):
            self.throttle.failed(name)

    def test_waits_only_after_the_limit(self):
        self.fail_login(FAILURE_LIMIT - 1)
        self.assertFalse(self.throttle.blocked("levi"))
        self.fail_login(1)
        self.assertTrue(self.throttle.blocked("levi"))

    def test_the_wait_ends(self):
        self.fail_login()
        self.now += WAIT_SECONDS + 1
        self.assertFalse(self.throttle.blocked("levi"))

    def test_one_name_does_not_affect_another(self):
        self.fail_login()
        self.assertFalse(self.throttle.blocked("tester"))


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.path = os.path.join(self.root, "users.json")

    def test_password_is_not_stored(self):
        accounts.set_password("levi", PASSWORD, self.path)
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn(PASSWORD, f.read())

    def test_check(self):
        accounts.set_password("Levi", PASSWORD, self.path)
        self.assertTrue(accounts.check("levi", PASSWORD, self.path))
        self.assertFalse(accounts.check("levi", "wrong password", self.path))
        self.assertFalse(accounts.check("nobody", PASSWORD, self.path))

    def test_refuses_unsafe_names_and_short_passwords(self):
        for name in ("..", "a/b", "a\\b", "", "-x", "x" * 33):
            with self.subTest(name), self.assertRaises(accounts.AccountError):
                accounts.set_password(name, PASSWORD, self.path)
        with self.assertRaises(accounts.AccountError):
            accounts.set_password("levi", "short", self.path)

    def test_unsafe_name_in_the_file_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"format": accounts.FORMAT, "users": {"../evil": {"password": "x"}}}, f)
        self.assertEqual(accounts.load(self.path), {})

    def test_remove(self):
        accounts.set_password("levi", PASSWORD, self.path)
        self.assertTrue(accounts.remove("levi", self.path))
        self.assertFalse(accounts.remove("levi", self.path))
        self.assertEqual(accounts.load(self.path), {})

    def test_names(self):
        self.assertEqual(accounts.names(self.path), [])
        accounts.set_password("tester", PASSWORD, self.path)
        accounts.set_password("Levi", PASSWORD, self.path)
        self.assertEqual(accounts.names(self.path), ["levi", "tester"])


if __name__ == "__main__":
    unittest.main()
