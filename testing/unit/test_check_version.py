"""
Tests for the version check (tools/check_version.py).

Run from app/:
    python3 -m unittest discover testing
"""

import unittest
from unittest import mock

from tools import check_version
from tools.check_version import find_versions, problems

TWO_PLACES = [("README.md", r"^Version (\d+\.\d+\.\d+)$"), ("version.py", r'^VERSION = "(.+)"$')]


class CheckVersionTest(unittest.TestCase):
    def test_finds_the_readme_version(self):
        found = find_versions(lambda name: "# CookbookAI\n\nVersion 1.0.1\n")
        self.assertEqual(found, {"README.md": "1.0.1"})
        self.assertEqual(problems(found), [])

    def test_matching_tag(self):
        self.assertEqual(problems({"README.md": "1.0.1"}, "v1.0.1"), [])

    def test_wrong_tag(self):
        self.assertEqual(problems({"README.md": "1.0.1"}, "v1.0.2"),
                         ["Tag v1.0.2 doesn't match the version written, 1.0.1"])

    def test_badly_formed_tag(self):
        self.assertEqual(len(problems({"README.md": "1.0.1"}, "1.0.1")), 1)
        self.assertEqual(len(problems({"README.md": "1.0.1"}, "v1.0")), 1)

    def test_missing_version(self):
        self.assertEqual(problems(find_versions(lambda name: "no version here")), ["README.md: no version found"])

    def test_places_that_disagree(self):
        files = {"README.md": "Version 1.0.1\n", "version.py": 'VERSION = "1.0.0"\n'}
        with mock.patch.object(check_version, "PLACES", TWO_PLACES):
            errors = problems(find_versions(files.get), "v1.0.1")
        self.assertEqual(errors, ["The places disagree: README.md says 1.0.1, version.py says 1.0.0"])

    def test_the_real_readme_has_a_version(self):
        self.assertEqual(problems(find_versions()), [])


if __name__ == "__main__":
    unittest.main()
