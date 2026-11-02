"""Stdlib tests for sub-issues-summary.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-reconcile/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "sub_issues_summary", pathlib.Path(__file__).with_name("sub-issues-summary.py")
)
sub_issues_summary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sub_issues_summary)


class FakeGh:
    def __init__(self, completed=2, total=3):
        self.summary = {"completed": completed, "total": total}
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        if args[:2] == ["issue", "view"]:
            return json.dumps({"id": f"NODE_{args[2]}"})
        if args[:2] == ["api", "graphql"]:
            assert "id=NODE_5" in args, args
            assert any("subIssuesSummary" in a for a in args), args
            return json.dumps({"data": {"node": {"subIssuesSummary": self.summary}}})
        raise AssertionError(f"unexpected gh call: {args}")


class SubIssuesSummary(unittest.TestCase):
    def test_given_open_work_then_completed_and_total_are_returned(self):
        sub_issues_summary.run_gh = FakeGh(completed=2, total=3)
        self.assertEqual(sub_issues_summary.sub_issues_summary(5), (2, 3))

    def test_given_no_sub_issues_then_zero_of_zero(self):
        sub_issues_summary.run_gh = FakeGh(completed=0, total=0)
        self.assertEqual(sub_issues_summary.sub_issues_summary(5), (0, 0))

    def test_the_summary_is_read_only(self):
        gh = FakeGh()
        sub_issues_summary.run_gh = gh
        sub_issues_summary.sub_issues_summary(5)
        self.assertFalse(any(c[:2] == ["issue", "edit"] for c in gh.calls))
        self.assertFalse(any("mutation" in a for c in gh.calls for a in c))

    def test_main_prints_completed_then_total(self):
        sub_issues_summary.run_gh = FakeGh(completed=4, total=4)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sub_issues_summary.main(["5"])
        self.assertEqual(out.getvalue(), "4 4\n")


if __name__ == "__main__":
    unittest.main()
