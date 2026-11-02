"""Stdlib unit tests for merge_pr's pure helpers. Run: python3 -m unittest scripts.test_merge_pr -v"""
import importlib.util
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "merge_pr", pathlib.Path(__file__).with_name("merge_pr.py")
)
merge_pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge_pr)


class ParseOwnerRepo(unittest.TestCase):
    def test_ssh_alias_host(self):
        self.assertEqual(
            merge_pr.parse_owner_repo("git@github.me:ghiblin/diet-pal.git"),
            "ghiblin/diet-pal",
        )

    def test_https(self):
        self.assertEqual(
            merge_pr.parse_owner_repo("https://github.com/ghiblin/diet-pal"),
            "ghiblin/diet-pal",
        )

    def test_garbage_raises(self):
        with self.assertRaises(SystemExit):
            merge_pr.parse_owner_repo("not-a-url")


class IssueNumberFromBranch(unittest.TestCase):
    def test_extracts_number(self):
        self.assertEqual(
            merge_pr.issue_number_from_branch("sdd/42-per-event-rescore-fix"), 42
        )

    def test_multi_digit(self):
        self.assertEqual(merge_pr.issue_number_from_branch("sdd/1234-x"), 1234)

    def test_non_sdd_branch_raises(self):
        with self.assertRaises(SystemExit):
            merge_pr.issue_number_from_branch("main")

    def test_no_number_raises(self):
        with self.assertRaises(SystemExit):
            merge_pr.issue_number_from_branch("sdd/foo-bar")


if __name__ == "__main__":
    unittest.main()
