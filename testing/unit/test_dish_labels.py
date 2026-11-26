import json
import os
import tempfile
import unittest
from unittest import mock

from match_utils import dish_labels
from tools.diagnostics import dish_labels as diagnostic

TYPES = {
    "cookie": {"about": "cookies", "title_words": ["cookie", "snickerdoodle"]},
    "pie": {"about": "pies", "title_words": ["pie"]},
    "chicken": {"about": "chicken dishes", "title_words": ["chicken"]},
    "dumpling": {"about": "dumplings", "title_words": ["dumpling"]},
}


def entry(recipe_id, title, ingredients=("flour", "sugar"), book="Test Book"):
    return {"recipe_id": recipe_id, "title": title, "match_title": title, "book": book,
            "ingredients": [{"name": n, "options": [n]} for n in ingredients]}


class Model:
    """A stand-in for ask_model: answers from a table, records each batch."""

    def __init__(self, answers, broken=()):
        self.answers, self.broken, self.batches = answers, set(broken), []

    def __call__(self, batch, types):
        self.batches.append([e["recipe_id"] for e in batch])
        if len(batch) > 1 and self.broken & {e["recipe_id"] for e in batch}:
            raise ValueError("unreadable")
        return {e["recipe_id"]: dish_labels.clean(self.answers.get(e["recipe_id"], []), types) for e in batch}


class TitleDishesTest(unittest.TestCase):
    def test_last_word_names_the_type(self):
        self.assertEqual(dish_labels.title_dishes(entry("a", "Brown Butter Snickerdoodles"), TYPES), ["cookie"])

    def test_with_tail_is_ignored(self):
        self.assertEqual(dish_labels.title_dishes(entry("a", "Pumpkin Pie with Gingersnap Cookie Crust"), TYPES),
                         ["pie"])

    def test_and_is_not_a_tail(self):
        self.assertEqual(dish_labels.title_dishes(entry("a", "Chicken and Dumplings"), TYPES), ["dumpling"])

    def test_only_the_last_word(self):
        self.assertEqual(dish_labels.title_dishes(entry("a", "Chicken Pot Pie"), TYPES), ["pie"])

    def test_nothing_named(self):
        self.assertEqual(dish_labels.title_dishes(entry("a", "Ratatouille"), TYPES), [])


class KeywordTest(unittest.TestCase):
    TYPES = {"seafood": {"keywords": ["salmon", "shrimp"]}, "pancake": {"keywords": ["crepe"]}, "cake": {}}

    def test_anywhere_in_the_title(self):
        self.assertEqual(dish_labels.title_keywords(entry("a", "Crispy Salmon Cakes"), self.TYPES), ["seafood"])
        self.assertEqual(dish_labels.title_keywords(entry("a", "Buckwheat Crepes Suzette"), self.TYPES), ["pancake"])
        self.assertEqual(dish_labels.title_keywords(entry("a", "Sugar Cookies"), self.TYPES), [])

    def test_added_to_the_models_types(self):
        entries = [entry("a", "Crispy Salmon Cakes")]
        dish_labels.label_dishes(entries, path=self.path, ask=Model({"a": ["dip"]}),
                                 types=self.TYPES | {"dip": {}}, log=lambda *_: None)
        self.assertEqual(entries[0]["dishes"], ["dip", "seafood"])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "dish_labels.json")

    def tearDown(self):
        self.dir.cleanup()


class LabelModelTest(unittest.TestCase):
    def test_label_model_when_pulled(self):
        with mock.patch.object(dish_labels, "LABEL_MODEL", "big"), mock.patch.object(dish_labels, "CHAT_MODEL", "small"),                 mock.patch.object(dish_labels.models, "installed", return_value=True):
            self.assertEqual(dish_labels.label_model(log=lambda *_: None), "big")

    def test_chat_model_when_not_pulled(self):
        messages = []
        with mock.patch.object(dish_labels, "LABEL_MODEL", "big"), mock.patch.object(dish_labels, "CHAT_MODEL", "small"),                 mock.patch.object(dish_labels.models, "installed", return_value=False):
            self.assertEqual(dish_labels.label_model(log=messages.append), "small")
        self.assertIn("ollama pull big", messages[0])

    def test_ollama_down_keeps_the_label_model(self):
        # It can't tell, and labeling then finds Ollama down on its own.
        with mock.patch.object(dish_labels, "LABEL_MODEL", "big"), mock.patch.object(dish_labels, "CHAT_MODEL", "small"),                 mock.patch.object(dish_labels.models, "installed", return_value=None):
            self.assertEqual(dish_labels.label_model(log=lambda *_: None), "big")

    def test_the_model_is_asked_for(self):
        with mock.patch.object(dish_labels.models, "chat", return_value=({"message": {"content": '{"1": []}'}}, 1)) as chat:
            dish_labels.ask_model([entry("a", "A")], TYPES, model="big")
        self.assertEqual(chat.call_args.kwargs["model"], "big")


class ImpliedTest(unittest.TestCase):
    def test_meat_kinds_add_meat(self):
        types = {"chicken": {"implies": ["meat"]}, "meat": {}, "soup": {}}
        self.assertEqual(dish_labels.with_implied({"chicken", "soup"}, types), ["chicken", "meat", "soup"])
        self.assertEqual(dish_labels.with_implied({"soup"}, types), ["soup"])

    def test_real_meat_kinds(self):
        types = dish_labels.load_types()
        for kind in ("chicken", "turkey", "beef", "pork", "lamb", "seafood"):
            with self.subTest(kind=kind):
                self.assertIn("meat", dish_labels.with_implied({kind}, types))


class CleanTest(unittest.TestCase):
    def test_unknown_types_dropped(self):
        self.assertEqual(dish_labels.clean(["Pie", "dessert", "pie", "chicken"], TYPES), ["pie", "chicken"])

    def test_a_string_is_one_type(self):
        self.assertEqual(dish_labels.clean("cookie", TYPES), ["cookie"])

    def test_not_a_list(self):
        self.assertEqual(dish_labels.clean({"x": 1}, TYPES), [])

    def test_at_most_three(self):
        types = {name: {} for name in "abcde"}
        self.assertEqual(dish_labels.clean(list("abcde"), types), ["a", "b", "c"])


class AskModelTest(unittest.TestCase):
    def reply(self, content):
        return mock.patch.object(dish_labels.models, "chat",
                                 return_value=({"message": {"content": content}}, 1.0))

    def test_numbers_map_to_recipes(self):
        batch = [entry("a", "Pot Pie"), entry("b", "Sugar Cookies")]
        with self.reply(json.dumps({"1": ["pie", "chicken"], "2": ["cookie", "bread"]})) as chat:
            self.assertEqual(dish_labels.ask_model(batch, TYPES), {"a": ["pie", "chicken"], "b": ["cookie"]})
        kwargs = chat.call_args.kwargs
        self.assertEqual(kwargs["format"], "json")
        self.assertIn("1. Pot Pie (Test Book) - ingredients: flour, sugar", kwargs["messages"][1]["content"])
        self.assertIn("- cookie: cookies", kwargs["messages"][0]["content"])

    def test_missing_recipe_left_out(self):
        with self.reply('{"1": ["pie"]}'):
            self.assertEqual(dish_labels.ask_model([entry("a", "A"), entry("b", "B")], TYPES), {"a": ["pie"]})

    def test_one_recipe_under_another_key(self):
        with self.reply('{"labels": ["pie", "dessert"]}'):
            self.assertEqual(dish_labels.ask_model([entry("a", "A")], TYPES), {"a": ["pie"]})

    def test_unreadable_reply(self):
        with self.reply("not json"), self.assertRaises(ValueError):
            dish_labels.ask_model([entry("a", "A")], TYPES)
        with self.reply("[1, 2]"), self.assertRaises(ValueError):
            dish_labels.ask_model([entry("a", "A")], TYPES)


class LabelDishesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "dish_labels.json")

    def tearDown(self):
        self.dir.cleanup()

    def label(self, entries, model, **kwargs):
        kwargs.setdefault("overrides", {})
        return dish_labels.label_dishes(entries, path=self.path, ask=model, types=TYPES, log=lambda *_: None,
                                        **kwargs)

    def test_title_only_when_the_model_gives_none(self):
        entries = [entry("a", "Chicken Pot Pie"), entry("b", "Ratatouille"), entry("c", "Apple Pie")]
        stats = self.label(entries, Model({"a": ["chicken"], "b": [], "c": []}))
        self.assertEqual([e["dishes"] for e in entries], [["chicken"], [], ["pie"]])
        self.assertEqual(stats, {"asked": 3, "kept": 0, "missing": 0})

    def test_model_types_only(self):
        entries = [entry("a", "Chicken Pot Pie"), entry("b", "Ratatouille")]
        stats = self.label(entries, Model({"a": ["chicken"], "b": []}))
        self.assertEqual(entries[0]["dishes"], ["chicken"])
        self.assertEqual(stats, {"asked": 2, "kept": 0, "missing": 0})

    def test_only_changed_recipes_asked_again(self):
        self.label([entry("a", "Pot Pie"), entry("b", "Cookies")], Model({"a": ["chicken"]}))
        model = Model({"b": ["cookie"]})
        entries = [entry("a", "Pot Pie"), entry("b", "Cookies", ingredients=["butter"])]
        stats = self.label(entries, model)
        self.assertEqual(model.batches, [["b"]])
        self.assertEqual(stats, {"asked": 1, "kept": 1, "missing": 0})
        self.assertEqual(entries[0]["dishes"], ["chicken"])

    def relabel(self, entries, model, types):
        return dish_labels.label_dishes(entries, path=self.path, ask=model, types=types, log=lambda *_: None,
                                        overrides={})

    def test_changed_type_asks_only_its_recipes(self):
        entries = [entry("a", "Pot Pie"), entry("b", "Snickerdoodles"), entry("c", "Chicken Soup")]
        self.label(entries, Model({"a": ["pie"], "b": ["cookie"], "c": []}))
        model = Model({"a": ["pie", "chicken"], "c": ["chicken"]})
        types = dict(TYPES, chicken={"about": "dishes built on chicken", "title_words": ["chicken"]})
        entries = [entry("a", "Pot Pie"), entry("b", "Snickerdoodles"), entry("c", "Chicken Soup")]
        stats = self.relabel(entries, model, types)
        # b has no chicken, so it isn't asked; c's title names it.
        self.assertEqual(model.batches, [["c"]])
        self.assertEqual(stats, {"asked": 1, "kept": 2, "missing": 0})
        self.assertEqual(entries[2]["dishes"], ["chicken"])

    def test_changed_type_asks_the_recipes_that_have_it(self):
        self.label([entry("a", "Pot Pie"), entry("b", "Cookies")], Model({"a": ["chicken"], "b": ["cookie"]}))
        model = Model({"a": ["pie"]})
        types = dict(TYPES, chicken={"about": "dishes built on chicken", "title_words": ["chicken"]})
        self.relabel([entry("a", "Pot Pie"), entry("b", "Cookies")], model, types)
        self.assertEqual(model.batches, [["a"]])

    def test_new_type_asks_the_titles_naming_it(self):
        self.label([entry("a", "Carrot Cake"), entry("b", "Cookies")], Model({"a": [], "b": ["cookie"]}))
        model = Model({"a": ["cake"]})
        types = dict(TYPES, cake={"about": "cakes", "title_words": ["cake"]})
        entries = [entry("a", "Carrot Cake"), entry("b", "Cookies")]
        self.relabel(entries, model, types)
        self.assertEqual(model.batches, [["a"]])
        self.assertEqual(entries[0]["dishes"], ["cake"])

    def test_fields_the_model_isnt_shown_ask_nothing_again(self):
        self.label([entry("a", "Pot Pie")], Model({"a": ["chicken"]}))
        model = Model({})
        types = dict(TYPES, chicken={"about": "chicken dishes", "title_words": ["chicken", "hen"],
                                     "keywords": ["poussin"]})
        self.relabel([entry("a", "Pot Pie")], model, types)
        self.assertEqual(model.batches, [])

    def test_cut_short_asks_the_rest_next_time(self):
        entries = [entry("a", "Pot Pie"), entry("b", "Pie")]
        self.label(entries, Model({"a": ["chicken"], "b": ["chicken"]}))
        types = dict(TYPES, chicken={"about": "dishes built on chicken"})
        seen = []

        def down_after_one(batch, types):
            seen.append(batch[0]["recipe_id"])
            if len(seen) > 1:
                raise ConnectionError("no ollama")
            return {batch[0]["recipe_id"]: ["pie"]}
        self.relabel([entry("a", "Pot Pie"), entry("b", "Pie")], down_after_one, types)
        model = Model({"b": ["pie"]})
        self.relabel([entry("a", "Pot Pie"), entry("b", "Pie")], model, types)
        self.assertEqual(model.batches, [["b"]])

    def test_new_prompt_relabels_everything(self):
        self.label([entry("a", "Pot Pie")], Model({"a": ["chicken"]}))
        model = Model({"a": ["pie"]})
        with mock.patch.object(dish_labels, "PROMPT", dish_labels.PROMPT + " "):
            self.label([entry("a", "Pot Pie")], model)
        self.assertEqual(model.batches, [["a"]])

    def test_new_model_relabels_everything(self):
        def run(ask, name):
            dish_labels.label_dishes([entry("a", "Pot Pie")], path=self.path, ask=ask, types=TYPES,
                                     log=lambda *_: None, model=name)
        run(Model({"a": ["chicken"]}), "one")
        asked = Model({"a": ["pie"]})
        run(asked, "other")
        self.assertEqual(asked.batches, [["a"]])

    def test_needs_name(self):
        types = dict(TYPES, doughnut={"about": "doughnuts", "title_words": ["doughnut", "beignet"],
                                      "needs_name": True})
        entries = [entry("a", "Ham Croissants"), entry("b", "Ricotta Beignets"),
                   dict(entry("c", "Let's Fry!"), chapter="4. Doughnuts")]
        self.relabel(entries, Model({"a": ["doughnut", "chicken"], "b": ["doughnut"], "c": ["doughnut"]}), types)
        self.assertEqual([e["dishes"] for e in entries], [["chicken"], ["doughnut"], ["doughnut"]])

    def test_needs_name_dropped_falls_back_on_the_title(self):
        types = dict(TYPES, doughnut={"about": "doughnuts", "title_words": ["doughnut"], "needs_name": True})
        entries = [entry("a", "Chicken Pie")]
        self.relabel(entries, Model({"a": ["doughnut"]}), types)
        self.assertEqual(entries[0]["dishes"], ["pie"])

    def test_override_replaces_the_labels(self):
        types = dict(TYPES, meat={"about": "meat"})
        types["chicken"] = dict(types["chicken"], implies=["meat"])
        entries = [entry("a", "Aunt Rose's  Mondel Bread"), entry("b", "Apple Pie")]
        overrides = {("aunt rose's mondel bread", "Test Book"): ["cookie", "chicken"]}
        dish_labels.label_dishes(entries, path=self.path, ask=Model({"a": ["pie"], "b": ["pie"]}), types=types,
                                 log=lambda *_: None, overrides=overrides)
        self.assertEqual([e["dishes"] for e in entries], [["chicken", "cookie", "meat"], ["pie"]])

    def test_override_only_in_its_book(self):
        entries = [entry("a", "Apple Pie", book="Other Book")]
        dish_labels.label_dishes(entries, path=self.path, ask=Model({"a": ["pie"]}), types=TYPES,
                                 log=lambda *_: None, overrides={("apple pie", "Test Book"): ["cookie"]})
        self.assertEqual(entries[0]["dishes"], ["pie"])

    def test_unreadable_batch_retried_one_at_a_time(self):
        entries = [entry("a", "A"), entry("b", "B")]
        model = Model({"a": ["pie"], "b": ["cookie"]}, broken={"b"})
        with mock.patch.object(dish_labels, "BATCH_SIZE", 2):
            self.label(entries, model)
        self.assertEqual(model.batches, [["a", "b"], ["a"], ["b"]])
        self.assertEqual([e["dishes"] for e in entries], [["pie"], ["cookie"]])

    def test_one_recipe_unreadable_gets_none(self):
        def model(batch, types):
            raise ValueError("unreadable")
        entries = [entry("a", "Apple Pie")]
        self.label(entries, model)
        self.assertEqual(entries[0]["dishes"], ["pie"])
        self.assertEqual(dish_labels.model_labels(self.path), {"a": []})

    def test_recipe_never_answered_gets_none(self):
        entries = [entry("a", "Apple Pie"), entry("b", "B")]
        model = Model({"a": ["pie"]})
        model_answers = model.__call__

        def skips_b(batch, types):
            return {k: v for k, v in model_answers(batch, types).items() if k != "b"}
        self.label(entries, skips_b)
        self.assertEqual(dish_labels.model_labels(self.path), {"a": ["pie"], "b": []})

    def test_model_down_keeps_saved_labels(self):
        self.label([entry("a", "Pot Pie")], Model({"a": ["chicken"]}))

        def down(batch, types):
            raise ConnectionError("no ollama")
        messages = []
        entries = [entry("a", "Pot Pie"), entry("b", "Snickerdoodles")]
        stats = dish_labels.label_dishes(entries, path=self.path, ask=down, types=TYPES, log=messages.append)
        self.assertEqual([e["dishes"] for e in entries], [["chicken"], ["cookie"]])
        self.assertEqual(stats, {"asked": 0, "kept": 1, "missing": 1})
        self.assertIn("couldn't be reached", messages[-1])

    def test_other_errors_are_raised(self):
        def broken(batch, types):
            raise KeyError("bug")
        with self.assertRaises(KeyError):
            self.label([entry("a", "A")], broken)

    def test_damaged_cache_starts_over(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        model = Model({"a": ["pie"]})
        self.label([entry("a", "A")], model)
        self.assertEqual(model.batches, [["a"]])


class DiagnosticTest(unittest.TestCase):
    def test_report(self):
        entries = [dict(entry("a", "Chicken Pot Pie"), dishes=["chicken", "pie"]),
                   dict(entry("b", "Sugar Cookies"), dishes=["cookie"]),
                   dict(entry("c", "Ratatouille"), dishes=[])]
        labels = {"a": ["chicken"], "b": ["cookie"], "c": []}
        text = "\n".join(diagnostic.report(entries, labels, TYPES, sample=1))
        self.assertIn("3 recipes, 2 with a dish type, 0 never labeled by the model", text)
        self.assertIn("  pie: 1 (0 by the model)  e.g. Chicken Pot Pie", text)
        self.assertIn("  Chicken Pot Pie (Test Book): title ['pie'], model ['chicken']", text)
        self.assertIn("No type at all (1):\n  Ratatouille (Test Book)", text)

    def test_judge(self):
        checked = {"types": ["salad", "egg dish"], "also": ["sandwich"]}
        self.assertEqual(diagnostic.judge(["salad", "sandwich"], checked), "right")
        self.assertEqual(diagnostic.judge(["salad", "soup"], checked), "partly")
        self.assertEqual(diagnostic.judge(["sandwich"], checked), "wrong")
        self.assertEqual(diagnostic.judge([], checked), "missing")

    def test_score_key(self):
        key = [{"title": "A", "book": "B", "types": ["pie"], "also": []},
               {"title": "C", "book": "B", "types": ["cake"], "also": []}]
        lines = diagnostic.score_key({("A", "B"): ["pie"], ("C", "B"): ["pie"]}, key)
        self.assertEqual(lines, ["1/2 right, 0 partly (a wrong type too), 1 wrong, 0 with no type",
                                 "  wrong: C (B): ['pie'], should be ['cake']"])

    def test_score_leaves_out_overrides(self):
        key = [{"title": "A", "book": "B", "types": ["pie"], "also": []},
               {"title": "C", "book": "B", "types": ["cake"], "also": []}]
        lines = diagnostic.score_key({("A", "B"): ["pie"], ("C", "B"): ["pie"]}, key, {("c", "B"): ["cake"]})
        self.assertEqual(lines, ["1/1 right, 0 partly (a wrong type too), 0 wrong, 0 with no type"
                                 " (1 left out: set by hand in the overrides)"])

    def test_overrides_use_known_types(self):
        types = dish_labels.load_types()
        for (title, _book), fixed in dish_labels.load_overrides().items():
            with self.subTest(title=title):
                self.assertTrue(fixed)
                self.assertLessEqual(set(fixed), set(types))

    def test_the_key_uses_known_types(self):
        types = dish_labels.load_types()
        for checked in diagnostic.load_key():
            with self.subTest(title=checked["title"]):
                self.assertTrue(checked["types"])
                self.assertLessEqual(set(checked["types"]) | set(checked["also"]), set(types))

    def test_one_type(self):
        entries = [dict(entry("a", "Chicken Pot Pie"), dishes=["chicken", "pie"])]
        self.assertEqual(diagnostic.report(entries, {"a": ["chicken"]}, TYPES, only="pie"),
                         ["pie: 1 recipes", "  Chicken Pot Pie (Test Book)  [title only]"])


if __name__ == "__main__":
    unittest.main()
