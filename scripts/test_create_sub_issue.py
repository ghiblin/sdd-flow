"""Stdlib tests for create-sub-issue.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "create_sub_issue", pathlib.Path(__file__).with_name("create-sub-issue.py")
)
create_sub_issue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_sub_issue)


class FakeGh:
    """Plays GitHub's side: issue create/view and the GraphQL sub-issue calls."""

    def __init__(self, child=77, nest_fails=False, nest_silently_dropped=False, drop_labels=()):
        self.child = child
        self.drop_labels = set(drop_labels)
        self.nest_fails = nest_fails
        self.nest_silently_dropped = nest_silently_dropped
        self.calls = []
        self.body = None
        self.labels = []
        self.title = None
        self.nested = []

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "create"]:
            self.title = args[args.index("--title") + 1]
            self.labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            self.body = stdin
            return f"https://github.com/o/r/issues/{self.child}"
        if args[:2] == ["issue", "view"]:
            if "labels" in args:
                assert args[2] == str(self.child), args
                kept = [{"name": n} for n in self.labels if n not in self.drop_labels]
                return json.dumps({"labels": kept})
            return json.dumps({"id": f"NODE_{args[2]}"})
        if args[:2] == ["api", "graphql"]:
            query = next(a for a in args if a.startswith("query="))
            if "addSubIssue" in query:
                if self.nest_fails:
                    raise SystemExit("gh api failed (1)")
                if not self.nest_silently_dropped:
                    self.nested.append(self.child)
                return json.dumps({"data": {"addSubIssue": {"issue": {"number": 5}}}})
            if "parent" in query:
                assert f"id=NODE_{self.child}" in args, args
                parent = {"number": 5} if self.child in self.nested else None
                return json.dumps({"data": {"node": {"parent": parent}}})
        raise AssertionError(f"unexpected gh call: {args}")


class CreateSubIssue(unittest.TestCase):
    def run_script(self, gh, title="Add the router — with → arrows"):
        create_sub_issue.run_gh = gh
        return create_sub_issue.create_sub_issue(5, title)

    def test_given_a_title_when_created_then_child_is_an_sdd_task_pointing_at_the_parent(self):
        gh = FakeGh()
        self.assertEqual(self.run_script(gh), 77)
        self.assertEqual(gh.title, "Add the router — with → arrows")
        self.assertEqual(gh.labels, ["sdd:task"])
        self.assertEqual(gh.body.strip(), "Part of #5")

    def test_body_is_sent_via_stdin(self):
        gh = FakeGh()
        self.run_script(gh)
        args, stdin = gh.calls[0]
        self.assertEqual(args[args.index("--body-file") + 1], "-")
        self.assertIn("#5", stdin)

    def test_given_the_child_exists_then_it_is_nested_by_node_ids(self):
        gh = FakeGh()
        self.run_script(gh)
        args, _ = next((a, s) for a, s in gh.calls if a[:2] == ["api", "graphql"])
        self.assertIn("p=NODE_5", args)
        self.assertIn("c=NODE_77", args)
        self.assertEqual(gh.nested, [77])

    def test_given_nesting_fails_then_it_exits_non_zero_naming_the_unnested_child(self):
        gh = FakeGh(nest_fails=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("#77", str(ctx.exception.code))
        self.assertIn("not nested", str(ctx.exception.code))

    def test_given_the_child_is_missing_from_the_parent_on_read_back_then_it_exits_non_zero(self):
        gh = FakeGh(nest_silently_dropped=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertIn("#77", str(ctx.exception.code))

    def test_nesting_is_verified_from_the_childs_parent_not_a_paged_child_list(self):
        gh = FakeGh()
        self.run_script(gh)
        queries = [next(x for x in a if x.startswith("query=")) for a, _ in gh.calls
                   if a[:2] == ["api", "graphql"]]
        self.assertTrue(any("parent" in q for q in queries))
        self.assertFalse(any("subIssues(" in q for q in queries))

    def test_given_an_unparseable_create_output_then_the_error_says_not_to_create_another(self):
        gh = FakeGh()

        def odd(args, stdin=None):
            if args[:2] == ["issue", "create"]:
                return "created, maybe"
            return gh(args, stdin)

        create_sub_issue.run_gh = odd
        with self.assertRaises(SystemExit) as ctx:
            create_sub_issue.create_sub_issue(5, "x")
        self.assertIn("was created", str(ctx.exception.code))
        self.assertIn("created, maybe", str(ctx.exception.code))

    def test_empty_title_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, title="  ")
        self.assertEqual(gh.calls, [])

    def test_main_prints_the_child_number(self):
        create_sub_issue.run_gh = FakeGh(child=81)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            create_sub_issue.main(["5", "--title", "x"])
        self.assertEqual(out.getvalue(), "81\n")

    def test_given_wip_scenarios_then_the_body_names_each_one_after_the_parent_line(self):
        # Given a sub-issue for a group of drafted @wip scenarios
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        # When it is created with those scenario names
        create_sub_issue.create_sub_issue(5, "x", scenarios=["Pick a plan — fast", "Reject → empty"])
        # Then the body keeps `Part of #5` and lists each scenario
        self.assertEqual(
            gh.body.strip(),
            "Part of #5\n\nScenarios:\n- `Pick a plan — fast`\n- `Reject → empty`",
        )

    def test_given_no_scenarios_then_the_body_is_only_the_parent_line(self):
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        create_sub_issue.create_sub_issue(5, "x", scenarios=[])
        self.assertEqual(gh.body.strip(), "Part of #5")

    def test_blank_scenario_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        with self.assertRaises(SystemExit):
            create_sub_issue.create_sub_issue(5, "x", scenarios=["ok", "  "])
        self.assertEqual(gh.calls, [])

    def test_mentions_and_issue_refs_in_scenario_names_are_code_spans(self):
        # Given scenario names holding an @-mention, an issue ref and a backtick
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        # When the sub-issue is created
        create_sub_issue.create_sub_issue(5, "x", scenarios=["Notify @admin on #12", "Run `cargo`"])
        # Then each name is a code span, so GitHub neither notifies nor links
        self.assertIn("- `Notify @admin on #12`\n- `` Run `cargo` ``", gh.body)

    def test_given_needs_spec_then_the_child_also_carries_the_needs_spec_label(self):
        # Given a sub-issue for work the spec section does not describe yet
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        # When it is created with --needs-spec
        child = create_sub_issue.create_sub_issue(5, "x", needs_spec=True)
        # Then it carries both sdd:task and sdd:needs-spec, read back from GitHub
        self.assertEqual(child, 77)
        self.assertEqual(gh.labels, ["sdd:task", "sdd:needs-spec"])
        self.assertTrue(any(a[:2] == ["issue", "view"] and "labels" in a for a, _ in gh.calls))

    def test_given_no_needs_spec_then_only_the_task_label_is_set(self):
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        create_sub_issue.create_sub_issue(5, "x")
        self.assertEqual(gh.labels, ["sdd:task"])

    def test_given_the_needs_spec_label_is_missing_on_read_back_then_it_exits_naming_the_child(self):
        gh = FakeGh(drop_labels={"sdd:needs-spec"})
        create_sub_issue.run_gh = gh
        with self.assertRaises(SystemExit) as ctx:
            create_sub_issue.create_sub_issue(5, "x", needs_spec=True)
        self.assertIn("#77", str(ctx.exception.code))
        self.assertIn("sdd:needs-spec", str(ctx.exception.code))

    def test_main_passes_the_needs_spec_flag(self):
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        with contextlib.redirect_stdout(io.StringIO()):
            create_sub_issue.main(["5", "--title", "x", "--needs-spec"])
        self.assertIn("sdd:needs-spec", gh.labels)

    def test_main_passes_every_scenario_flag(self):
        gh = FakeGh()
        create_sub_issue.run_gh = gh
        with contextlib.redirect_stdout(io.StringIO()):
            create_sub_issue.main(["5", "--title", "x", "--scenario", "A", "--scenario", "B"])
        self.assertIn("- `A`\n- `B`", gh.body)


if __name__ == "__main__":
    unittest.main()
