"""Stdlib tests for create-issue.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-intent/scripts -v
"""
import importlib.util
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "create_issue", pathlib.Path(__file__).with_name("create-issue.py")
)
create_issue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_issue)


class FakeGh:
    """Records every `gh` call and plays GitHub's side of the issue."""

    def __init__(self, number=42, corrupt_on_read=False):
        self.number = number
        self.corrupt_on_read = corrupt_on_read
        self.calls = []
        self.body = None
        self.labels = []

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "create"]:
            self.body = stdin
            self.labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            return f"https://github.com/o/r/issues/{self.number}"
        if args[:2] == ["issue", "edit"]:
            self.body = stdin
            return ""
        if args[:2] == ["issue", "view"]:
            body = self.body.replace("—", "â€”") if self.corrupt_on_read else self.body
            return json.dumps(
                {"body": body, "labels": [{"name": n} for n in self.labels]}
            )
        raise AssertionError(f"unexpected gh call: {args}")


class CreateIssue(unittest.TestCase):
    def run_script(self, gh, decisions=()):
        create_issue.run_gh = gh
        return create_issue.create_issue(
            slug="add-router",
            intent="Add a router — with arrows → and Niccolò",
            spec_files=["docs/specs/crates/dietpal-agent.md", "docs/specs/server/chat-api.md"],
            decisions=list(decisions),
        )

    def test_given_an_intent_when_created_then_issue_has_feature_and_stage_labels(self):
        gh = FakeGh()
        self.run_script(gh)
        create_args = gh.calls[0][0]
        self.assertEqual(create_args[:4], ["issue", "create", "--title", "add-router"])
        self.assertEqual(gh.labels, ["sdd:feature", "sdd:stage:drafting-spec"])

    def test_given_a_created_issue_then_body_branch_carries_the_real_number(self):
        gh = FakeGh(number=77)
        number = self.run_script(gh)
        self.assertEqual(number, 77)
        self.assertIn("**Branch:** sdd/77-add-router\n", gh.body)
        self.assertEqual(gh.calls[1][0][:3], ["issue", "edit", "77"])

    def test_body_matches_the_template_with_no_leading_whitespace(self):
        gh = FakeGh(number=5)
        self.run_script(gh, decisions=["Which trait?"])
        self.assertEqual(
            gh.body,
            "<!-- sdd:begin -->\n"
            "**Intent:** Add a router — with arrows → and Niccolò\n"
            "**Stage:** drafting-spec\n"
            "**Worktree:** .claude/worktrees/add-router\n"
            "**Branch:** sdd/5-add-router\n"
            "**Spec files:** docs/specs/crates/dietpal-agent.md, docs/specs/server/chat-api.md\n"
            "## Open decisions\n"
            "- [ ] Which trait?\n"
            "<!-- sdd:end -->\n",
        )

    def test_no_decisions_renders_the_none_placeholder(self):
        gh = FakeGh()
        self.run_script(gh)
        self.assertIn("## Open decisions\n- [ ] _none_\n<!-- sdd:end -->", gh.body)

    def test_body_is_sent_as_utf8_text_via_stdin(self):
        gh = FakeGh()
        self.run_script(gh)
        for args, stdin in gh.calls[:2]:
            self.assertIn("--body-file", args)
            self.assertEqual(args[args.index("--body-file") + 1], "-")
            self.assertIn("Niccolò", stdin)

    def test_given_the_read_back_differs_then_the_error_says_not_to_create_another(self):
        gh = FakeGh(number=93, corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertIn("#93", str(ctx.exception.code))
        self.assertIn("instead of creating another", str(ctx.exception.code))

    def test_given_the_read_back_differs_then_it_exits_non_zero(self):
        gh = FakeGh(corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_given_an_unparseable_create_output_then_it_exits_non_zero(self):
        gh = FakeGh()
        gh_call = gh.__call__

        def broken(args, stdin=None):
            if args[:2] == ["issue", "create"]:
                return "something went wrong"
            return gh_call(args, stdin)

        create_issue.run_gh = broken
        with self.assertRaises(SystemExit) as ctx:
            create_issue.create_issue("s", "i", ["a.md"], [])
        self.assertIn("was created", str(ctx.exception.code))
        self.assertIn("something went wrong", str(ctx.exception.code))

    def test_given_a_malformed_read_back_then_the_error_names_the_created_issue(self):
        gh = FakeGh(number=92)

        def garbled(args, stdin=None):
            if args[:2] == ["issue", "view"]:
                return "warning: not json"
            return gh(args, stdin)

        create_issue.run_gh = garbled
        with self.assertRaises(SystemExit) as ctx:
            create_issue.create_issue("add-router", "Add a router", ["docs/specs/crates/workspace.md"], [])
        self.assertIn("#92", str(ctx.exception.code))
        self.assertIn("could not be verified", str(ctx.exception.code))

    def test_blank_intent_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        create_issue.run_gh = gh
        with self.assertRaises(SystemExit):
            create_issue.create_issue("add-router", "  ", ["docs/specs/crates/workspace.md"], [])
        self.assertEqual(gh.calls, [])

    def test_no_spec_files_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        create_issue.run_gh = gh
        with self.assertRaises(SystemExit):
            create_issue.create_issue("add-router", "Add a router", [], [])
        self.assertEqual(gh.calls, [])

    def test_multi_line_intent_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        create_issue.run_gh = gh
        with self.assertRaises(SystemExit):
            create_issue.create_issue("add-router", "Add\nStray", ["docs/specs/crates/workspace.md"], [])
        self.assertEqual(gh.calls, [])

    def test_multi_line_decision_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, decisions=["A or B?\nContext: more"])
        self.assertEqual(gh.calls, [])

    def test_given_a_failure_after_create_then_the_error_names_the_created_issue(self):
        gh = FakeGh(number=91)

        def failing(args, stdin=None):
            if args[:2] == ["issue", "edit"]:
                raise SystemExit("gh issue edit failed (1)")
            return gh(args, stdin)

        create_issue.run_gh = failing
        with self.assertRaises(SystemExit) as ctx:
            create_issue.create_issue(
                "add-router", "Add a router", ["docs/specs/crates/workspace.md"], []
            )
        self.assertIn("#91", str(ctx.exception.code))
        self.assertIn("not finalized", str(ctx.exception.code))

    def test_slug_must_be_kebab_case(self):
        create_issue.run_gh = FakeGh()
        with self.assertRaises(SystemExit):
            create_issue.create_issue("Not A Slug", "i", ["a.md"], [])


class Cli(unittest.TestCase):
    def test_main_prints_the_issue_number(self):
        gh = FakeGh(number=9)
        create_issue.run_gh = gh
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            create_issue.main(
                [
                    "--slug", "x-y",
                    "--intent", "do it",
                    "--spec-file", "docs/specs/domain/patient.md",
                    "--spec-file", "docs/specs/domain/task.md",
                    "--decision", "Q1?",
                    "--decision", "Q2?",
                ]
            )
        self.assertEqual(out.getvalue().strip(), "9")
        self.assertIn("- [ ] Q1?\n- [ ] Q2?\n", gh.body)
        self.assertIn("**Spec files:** docs/specs/domain/patient.md, docs/specs/domain/task.md\n", gh.body)


if __name__ == "__main__":
    unittest.main()
