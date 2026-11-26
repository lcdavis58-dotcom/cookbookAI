import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from tools import run_evals


def candidate(title):
    return SimpleNamespace(title=title)


def turn(label="rule: ask list", how="rule", text="", result=None):
    return SimpleNamespace(route=SimpleNamespace(label=label, how=how), text=text, result=result)


def choices(*titles, rest=()):
    return SimpleNamespace(kind="choices", choices=[candidate(t) for t in titles],
                           rest=[candidate(t) for t in rest], recipe=None)


class CasesFileTest(unittest.TestCase):
    def test_every_case_is_well_formed(self):
        cases = run_evals.load_cases()
        ids = [c["id"] for c in cases]
        self.assertEqual(len(ids), len(set(ids)), "case ids repeat")
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["message"].strip())
                self.assertRegex(case["since"], r"^\d+\.\d+\.\d+$")
                self.assertTrue(case["expect"], "a case needs something to check")
                self.assertLessEqual(set(case["expect"]), set(run_evals.CHECKS))
                self.assertIsInstance(case.get("setup", []), list)


class ScoreTest(unittest.TestCase):
    def test_passes(self):
        case = {"expect": {"route": "rule: ask", "how": "rule", "titles": ["A"], "not_titles": ["C"], "count": 3,
                           "reply": ["have 3"], "not_reply": ["scale"]}}
        self.assertEqual(run_evals.score(case, turn(text="You have 3", result=choices("A", "B", rest=["D"]))), [])

    def test_each_check_can_fail(self):
        case = {"expect": {"route": "rule: scale", "how": "model", "titles": ["Z"], "not_titles": ["A"], "count": 1,
                           "reply": ["nope"], "not_reply": ["You"]}}
        failed = run_evals.score(case, turn(text="You have 2", result=choices("A", "B")))
        self.assertEqual([f.split(":")[0] for f in failed],
                         ["route", "how", "titles", "not_titles", "count", "reply", "not_reply"])

    def test_recipe_and_factor(self):
        scaled = SimpleNamespace(kind="scaled", recipe=candidate("Pie"), factor=2.0)
        self.assertEqual(run_evals.score({"expect": {"recipe": "Pie", "factor": 2.0}}, turn(result=scaled)), [])
        self.assertEqual(len(run_evals.score({"expect": {"recipe": "Tart", "factor": 3}}, turn(result=scaled))), 2)

    def test_books_cited(self):
        answer = SimpleNamespace(kind="answer", sources=[{"book": "A"}, {"book": "B"}])
        self.assertEqual(run_evals.score({"expect": {"books": ["A", "B", "C"]}}, turn(result=answer)), [])
        self.assertEqual(run_evals.score({"expect": {"books": ["A"]}}, turn(result=answer)), ["books: cited ['B']"])

    def test_match_results_are_listed(self):
        matches = SimpleNamespace(kind="matches", ready=[{"entry": {"title": "Pie"}}], from_scratch=[],
                                  missing_some=[{"entry": {"title": "Tart"}}])
        self.assertEqual(run_evals.score({"expect": {"titles": ["Pie", "Tart"], "count": 2}}, turn(result=matches)), [])

    def test_a_plain_reply(self):
        self.assertEqual(run_evals.score({"expect": {"route": "rule: reply"}}, turn("rule: reply none")), [])


class RunAndSaveTest(unittest.TestCase):
    def test_setup_then_scored(self):
        sent = []

        def respond(state, message):
            sent.append(message)
            return turn(text=f"got {message}")
        result = run_evals.run_case({"id": "x", "setup": ["one"], "message": "two", "expect": {"reply": ["got two"]}},
                                    respond)
        self.assertEqual(sent, ["one", "two"])
        self.assertEqual((result["id"], result["failed"]), ("x", []))

    def test_a_crash_fails_the_case(self):
        def respond(state, message):
            raise KeyError("boom")
        result = run_evals.run_case({"id": "x", "message": "m", "expect": {"reply": ["y"]}}, respond)
        self.assertEqual(result["failed"], ["error: KeyError: 'boom'"])

    def test_summary_and_saved_file(self):
        results = [{"id": "a", "failed": [], "route": "rule: ask", "seconds": 0.1, "model_seconds": 0},
                   {"id": "b", "failed": ["route: x"], "route": "model: ask", "seconds": 2, "model_seconds": 1.5}]
        lines = run_evals.summarize(results)
        self.assertEqual(lines[:3], ["1/2 passed (50%)", "1 routed by the model, 1 by rules or a pending question",
                                     "model time: 1.5s in all"])
        self.assertIn("  FAIL b  [model: ask]", lines)
        checked = results + [dict(results[1], checks=[[]]), dict(results[1], checks=[[{"kind": "page"}], []]),
                             dict(results[1], checks=[[{"kind": "page"}], [{"kind": "page"}]])]
        self.assertIn("3 model answers checked: 1 passed at once, 2 asked again, 1 still shown with a warning",
                      run_evals.summarize(checked))
        with tempfile.TemporaryDirectory() as directory:
            path = run_evals.save(results, "1.2.0", "qwen2.5:7b", directory)
            self.assertTrue(os.path.basename(path).startswith("1.2.0_qwen2.5-7b_"))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["results"], results)


if __name__ == "__main__":
    unittest.main()
