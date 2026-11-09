"""
Tests for the website (web/), using Flask's test client on temporary
folders. Nothing here needs the database or a model.

Run from app/:
    python3 -m unittest discover testing
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from testing.unit.test_chat_router import CANDIDATES  # (also stubs chromadb/ollama)

from chat import store  # noqa: E402
from chat.state import ChatState, RecipeRef  # noqa: E402
from common import accounts  # noqa: E402
from web import create_app  # noqa: E402
from web.auth import FAILURE_LIMIT, WAIT_SECONDS, Throttle  # noqa: E402

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
        wrong = self.sign_in(password="nope nope")
        unknown = self.sign_in(name="nobody")
        self.assertEqual((wrong.status_code, wrong.get_data()), (401, unknown.get_data()))
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

    def fail(self, times=FAILURE_LIMIT, name="levi"):
        for _ in range(times):
            self.throttle.failed(name)

    def test_waits_only_after_the_limit(self):
        self.fail(FAILURE_LIMIT - 1)
        self.assertFalse(self.throttle.blocked("levi"))
        self.fail(1)
        self.assertTrue(self.throttle.blocked("levi"))

    def test_the_wait_ends(self):
        self.fail()
        self.now += WAIT_SECONDS + 1
        self.assertFalse(self.throttle.blocked("levi"))

    def test_one_name_does_not_affect_another(self):
        self.fail()
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


if __name__ == "__main__":
    unittest.main()
