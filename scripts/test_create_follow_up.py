"""Stdlib tests for create-follow-up.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "create_follow_up", pathlib.Path(__file__).with_name("create-follow-up.py")
)
create_follow_up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_follow_up)

FINDING = "follow-up: docs/a.md:12 — the @wip clause → no edge case for `x`"


class FakeGh:
    """Plays GitHub's side: issue create and the read-back of the new issue."""

    def __init__(self, number=91, drop_label=False, body_override=None, url=None, label_exists=True,
                 create_fails=False, created_elsewhere=False):
        self.label_exists = label_exists
        self.create_fails = create_fails
        self.created_elsewhere = created_elsewhere
        self.number = number
        self.drop_label = drop_label
        self.body_override = body_override
        self.url = url
        self.calls = []
        self.title = None
        self.labels = []
        self.body = None

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["label", "list"]:
            return json.dumps([{"name": "sdd:follow-up"}] if self.label_exists else [{"name": "sdd:task"}])
        if args[:2] == ["label", "create"]:
            if self.create_fails:
                if self.created_elsewhere:
                    self.label_exists = True
                raise SystemExit("gh label create failed (1)")
            return ""
        if args[:2] == ["issue", "create"]:
            self.title = args[args.index("--title") + 1]
            self.labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            self.body = stdin
            return self.url or f"https://github.com/o/r/issues/{self.number}"
        if args[:2] == ["issue", "view"]:
            assert args[2] == str(self.number), args
            labels = [] if self.drop_label else [{"name": n} for n in self.labels]
            body = self.body if self.body_override is None else self.body_override
            return json.dumps({"labels": labels, "body": body})
        raise AssertionError(f"unexpected gh call: {args}")


class CreateFollowUp(unittest.TestCase):
    def run_script(self, gh, title="Cover the empty list — edge case", finding=FINDING):
        create_follow_up.run_gh = gh
        return create_follow_up.create_follow_up(353, title, finding)

    def test_given_a_finding_when_filed_then_the_issue_has_the_follow_up_label_only(self):
        gh = FakeGh()
        self.assertEqual(self.run_script(gh), 91)
        self.assertEqual(gh.title, "Cover the empty list — edge case")
        self.assertEqual(gh.labels, ["sdd:follow-up"])

    def test_body_starts_with_the_follow_up_line_then_gives_the_finding(self):
        gh = FakeGh()
        self.run_script(gh)
        lines = gh.body.splitlines()
        self.assertEqual(lines[0], "Follow-up from #353")
        self.assertIn(FINDING, gh.body)

    def test_finding_is_fenced_so_mentions_and_refs_neither_notify_nor_link(self):
        gh = FakeGh()
        self.run_script(gh, finding="see @wip and #12 and ``` fences")
        after = gh.body.split("\n", 1)[1]
        fence = "````"
        self.assertIn(f"\n{fence}text\nsee @wip and #12 and ``` fences\n{fence}\n", after)

    def test_body_is_sent_via_stdin(self):
        gh = FakeGh()
        self.run_script(gh)
        args, stdin = next(c for c in gh.calls if c[0][:2] == ["issue", "create"])
        self.assertEqual(args[args.index("--body-file") + 1], "-")
        self.assertTrue(stdin.startswith("Follow-up from #353"))

    def test_given_a_missing_label_then_it_is_created_before_the_issue(self):
        gh = FakeGh(label_exists=False)
        self.run_script(gh)
        kinds = [a[:2] for a, _ in gh.calls]
        self.assertLess(kinds.index(["label", "create"]), kinds.index(["issue", "create"]))
        args = gh.calls[kinds.index(["label", "create"])][0]
        self.assertEqual(args[2], "sdd:follow-up")
        self.assertNotIn("--force", args)

    def test_given_another_run_created_the_label_first_then_the_issue_is_still_filed(self):
        gh = FakeGh(label_exists=False, create_fails=True, created_elsewhere=True)
        self.assertEqual(self.run_script(gh), 91)
        self.assertIn(["issue", "create"], [a[:2] for a, _ in gh.calls])

    def test_given_the_label_create_fails_and_no_label_exists_then_nothing_is_filed(self):
        gh = FakeGh(label_exists=False, create_fails=True)
        with self.assertRaises(SystemExit):
            self.run_script(gh)
        self.assertNotIn(["issue", "create"], [a[:2] for a, _ in gh.calls])

    def test_given_the_create_and_the_re_read_both_fail_then_the_create_error_is_reported(self):
        gh = FakeGh(label_exists=False, create_fails=True)
        calls = {"list": 0}
        inner = gh.__call__

        def flaky(args, stdin=None):
            if args[:2] == ["label", "list"]:
                calls["list"] += 1
                if calls["list"] > 1:
                    raise SystemExit("gh label list failed (1)")
            return inner(args, stdin)

        create_follow_up.run_gh = flaky
        with self.assertRaises(SystemExit) as ctx:
            create_follow_up.create_follow_up(353, "t", "f")
        self.assertIn("label create", str(ctx.exception.code))

    def test_given_an_existing_label_then_it_is_not_created_or_changed(self):
        gh = FakeGh(label_exists=True)
        self.run_script(gh)
        kinds = [a[:2] for a, _ in gh.calls]
        self.assertIn(["label", "list"], kinds)
        self.assertNotIn(["label", "create"], kinds)

    def test_it_is_not_a_sub_issue(self):
        gh = FakeGh()
        self.run_script(gh)
        self.assertFalse(any(a[:2] == ["api", "graphql"] for a, _ in gh.calls))
        self.assertNotIn("sdd:task", gh.labels)

    def test_the_new_issue_is_re_read(self):
        gh = FakeGh()
        self.run_script(gh)
        views = [a for a, _ in gh.calls if a[:2] == ["issue", "view"]]
        self.assertEqual(len(views), 1)
        self.assertIn("labels,body", views[0])

    def test_given_the_label_did_not_land_then_it_exits_non_zero_naming_the_issue(self):
        gh = FakeGh(drop_label=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertIn("#91", str(ctx.exception.code))
        self.assertIn("sdd:follow-up", str(ctx.exception.code))

    def test_given_the_first_body_line_did_not_land_then_it_exits_non_zero(self):
        gh = FakeGh(body_override="something else\n\nFollow-up from #353")
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertIn("#91", str(ctx.exception.code))
        self.assertIn("Follow-up from #353", str(ctx.exception.code))

    def test_given_a_crlf_body_then_the_first_line_still_matches(self):
        gh = FakeGh(body_override="Follow-up from #353\r\n\r\nx")
        self.assertEqual(self.run_script(gh), 91)

    def test_given_an_unreadable_url_then_it_exits_without_filing_another(self):
        gh = FakeGh(url="created")
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertIn("instead of creating another", str(ctx.exception.code))
        self.assertEqual(sum(1 for a, _ in gh.calls if a[:2] == ["issue", "create"]), 1)

    def test_given_a_blank_title_then_nothing_is_created(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, title="  ")
        self.assertEqual(gh.calls, [])

    def test_given_a_blank_finding_then_nothing_is_created(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, finding="\n ")
        self.assertEqual(gh.calls, [])

    def test_main_prints_the_new_issue_number(self):
        gh = FakeGh(number=92)
        create_follow_up.run_gh = gh
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            create_follow_up.main(["353", "--title", "t", "--finding", "f"])
        self.assertEqual(out.getvalue().strip(), "92")


if __name__ == "__main__":
    unittest.main()
