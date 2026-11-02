"""Stdlib tests for list-sub-issues.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "list_sub_issues", pathlib.Path(__file__).with_name("list-sub-issues.py")
)
list_sub_issues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(list_sub_issues)

NODES = [
    {"number": 8, "title": "First — done", "state": "CLOSED"},
    {"number": 9, "title": "Second → open", "state": "OPEN"},
    {"number": 10, "title": "Third", "state": "OPEN"},
]


class FakeGh:
    """Serves the sub-issues in pages of `page` nodes, cursor = next start index."""

    def __init__(self, nodes=NODES, page=100):
        self.nodes = nodes
        self.page = page
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        if args[:2] == ["issue", "view"]:
            return json.dumps({"id": f"NODE_{args[2]}"})
        if args[:2] == ["api", "graphql"]:
            assert "id=NODE_5" in args, args
            after = next((a[len("after="):] for a in args if a.startswith("after=")), "")
            start = int(after) if after else 0
            end = start + self.page
            info = {"hasNextPage": end < len(self.nodes), "endCursor": str(end)}
            sub = {"nodes": self.nodes[start:end], "pageInfo": info}
            return json.dumps({"data": {"node": {"subIssues": sub}}})
        raise AssertionError(f"unexpected gh call: {args}")


class ListSubIssues(unittest.TestCase):
    def test_given_sub_issues_then_all_are_returned_in_order(self):
        list_sub_issues.run_gh = FakeGh()
        self.assertEqual(list_sub_issues.list_sub_issues(5), NODES)

    def test_given_open_only_then_closed_ones_are_dropped(self):
        list_sub_issues.run_gh = FakeGh()
        self.assertEqual(
            [s["number"] for s in list_sub_issues.list_sub_issues(5, open_only=True)], [9, 10]
        )

    def test_given_no_sub_issues_then_the_list_is_empty(self):
        list_sub_issues.run_gh = FakeGh(nodes=[])
        self.assertEqual(list_sub_issues.list_sub_issues(5), [])

    def test_given_more_sub_issues_than_one_page_then_every_page_is_read(self):
        many = [{"number": i, "title": f"T{i}", "state": "OPEN"} for i in range(1, 251)]
        list_sub_issues.run_gh = FakeGh(nodes=many, page=100)
        self.assertEqual(list_sub_issues.list_sub_issues(5), many)

    def test_main_prints_one_tab_separated_line_per_sub_issue(self):
        list_sub_issues.run_gh = FakeGh()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            list_sub_issues.main(["5"])
        self.assertEqual(
            out.getvalue(),
            "8\tCLOSED\tFirst — done\n9\tOPEN\tSecond → open\n10\tOPEN\tThird\n",
        )

    def test_main_open_flag_prints_only_open_ones(self):
        list_sub_issues.run_gh = FakeGh()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            list_sub_issues.main(["5", "--open"])
        self.assertEqual(out.getvalue(), "9\tOPEN\tSecond → open\n10\tOPEN\tThird\n")


if __name__ == "__main__":
    unittest.main()
