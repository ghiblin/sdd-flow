"""Stdlib tests for needs-spec.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "needs_spec", pathlib.Path(__file__).with_name("needs-spec.py")
)
needs_spec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(needs_spec)

LABEL = "sdd:needs-spec"


def sub(number, state="OPEN", labels=("sdd:task",), body="Part of #5\n"):
    return {
        "number": number, "state": state, "labels": list(labels), "body": body,
        "title": f"Task {number}",
    }


class FakeGh:
    """Plays the main issue #5 and its sub-issues; pages the sub-issue listing."""

    def __init__(self, subs, page=100, edit_drops=False, body_drops=False):
        self.subs = {s["number"]: s for s in subs}
        self.order = [s["number"] for s in subs]
        self.page = page
        self.edit_drops = edit_drops
        self.body_drops = body_drops
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "view"] and args[2] == "5":
            return json.dumps({"id": "NODE_5"})
        if args[:2] == ["issue", "view"]:
            s = self.subs[int(args[2])]
            return json.dumps(
                {"body": s["body"], "labels": [{"name": n} for n in s["labels"]]}
            )
        if args[:2] == ["api", "graphql"]:
            assert "id=NODE_5" in args, args
            after = next((a[len("after="):] for a in args if a.startswith("after=")), "")
            start = int(after) if after else 0
            end = start + self.page
            nodes = [
                {
                    "number": n,
                    "title": self.subs[n]["title"],
                    "state": self.subs[n]["state"],
                    "labels": {"nodes": [{"name": x} for x in self.subs[n]["labels"]]},
                }
                for n in self.order[start:end]
            ]
            info = {"hasNextPage": end < len(self.order), "endCursor": str(end)}
            return json.dumps(
                {"data": {"node": {"subIssues": {"nodes": nodes, "pageInfo": info}}}}
            )
        if args[:2] == ["issue", "edit"]:
            if self.edit_drops:
                return ""
            s = self.subs[int(args[2])]
            if "--remove-label" in args:
                gone = args[args.index("--remove-label") + 1]
                s["labels"] = [n for n in s["labels"] if n != gone]
            if "--body-file" in args and not self.body_drops:
                s["body"] = stdin
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


class ListNeedsSpec(unittest.TestCase):
    def test_given_open_labelled_sub_issues_then_only_their_numbers_are_listed(self):
        # Given open, closed, labelled and unlabelled sub-issues
        gh = FakeGh([
            sub(8, labels=("sdd:task", LABEL)),
            sub(9),
            sub(10, state="CLOSED", labels=("sdd:task", LABEL)),
            sub(11, labels=(LABEL, "sdd:task")),
        ])
        needs_spec.run_gh = gh
        # When the main issue is checked
        # Then only the open ones that carry sdd:needs-spec come back, in order
        self.assertEqual(needs_spec.needs_spec(5), [8, 11])

    def test_every_page_is_read(self):
        gh = FakeGh([sub(n, labels=("sdd:task", LABEL)) for n in range(1, 6)], page=2)
        needs_spec.run_gh = gh
        self.assertEqual(needs_spec.needs_spec(5), [1, 2, 3, 4, 5])

    def test_given_none_then_main_prints_nothing(self):
        needs_spec.run_gh = FakeGh([sub(8)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            needs_spec.main(["5"])
        self.assertEqual(out.getvalue(), "")

    def test_titles_prints_number_tab_title(self):
        needs_spec.run_gh = FakeGh([sub(8, labels=(LABEL,)), sub(9)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            needs_spec.main(["5", "--titles"])
        self.assertEqual(out.getvalue(), "8\tTask 8\n")

    def test_main_prints_one_number_per_line(self):
        needs_spec.run_gh = FakeGh([sub(8, labels=(LABEL,)), sub(9, labels=(LABEL,))])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            needs_spec.main(["5"])
        self.assertEqual(out.getvalue(), "8\n9\n")


class ClearNeedsSpec(unittest.TestCase):
    def test_given_scenarios_then_the_label_goes_and_the_body_lists_them(self):
        # Given an open sdd:needs-spec sub-issue
        gh = FakeGh([sub(8, labels=("sdd:task", LABEL), body="Part of #5\n")])
        needs_spec.run_gh = gh
        # When the draft clears it with the scenarios it drafted
        needs_spec.clear(5, 8, ["Pick a plan — fast", "Notify @admin on #12"])
        # Then the label is gone and the names follow a Scenarios: line as code spans
        self.assertEqual(gh.subs[8]["labels"], ["sdd:task"])
        self.assertEqual(
            gh.subs[8]["body"].strip(),
            "Part of #5\n\nScenarios:\n- `Pick a plan — fast`\n- `Notify @admin on #12`",
        )

    def test_given_an_existing_scenarios_list_then_the_names_replace_it(self):
        body = "Part of #5\r\n\r\nScenarios:\r\n- `Old one`\r\n- `Gone`\r\n\r\nNotes\r\n"
        gh = FakeGh([sub(8, labels=("sdd:task", LABEL), body=body)])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, ["New one", "Old one"])
        self.assertEqual(
            gh.subs[8]["body"].strip(),
            "Part of #5\n\nScenarios:\n- `New one`\n- `Old one`\n\nNotes",
        )

    def test_given_a_name_twice_then_it_is_listed_once(self):
        gh = FakeGh([sub(8, labels=(LABEL,))])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, ["A", "A"])
        self.assertEqual(gh.subs[8]["body"].count("- `A`"), 1)

    def test_given_the_label_is_gone_already_then_a_re_run_records_the_scenarios(self):
        # Given an open sub-issue whose label an earlier clear (or first scoped draft) removed
        gh = FakeGh([sub(8, body="Part of #5\n\nScenarios:\n- `Old`\n")])
        needs_spec.run_gh = gh
        # When the clear runs again (a re-run, or a "Request changes" repeat)
        needs_spec.clear(5, 8, ["Renamed"])
        # Then it removes no label and the list names only the new scenarios
        edit = next(a for a, _ in gh.calls if a[:2] == ["issue", "edit"])
        self.assertNotIn("--remove-label", edit)
        self.assertEqual(gh.subs[8]["body"].strip(), "Part of #5\n\nScenarios:\n- `Renamed`")

    def test_given_no_scenarios_on_a_repeat_then_the_stale_list_is_removed(self):
        # Given a sub-issue whose first scoped draft recorded a scenario
        gh = FakeGh([sub(8, body="Part of #5\n\nScenarios:\n- `Old`\n\nNotes\n")])
        needs_spec.run_gh = gh
        # When the repeat drops that scenario and clears with no --scenario
        needs_spec.clear(5, 8, [])
        # Then the Scenarios: line and its list are gone
        self.assertEqual(gh.subs[8]["body"], "Part of #5\n\nNotes\n")

    def test_a_blank_line_or_trailing_space_after_the_heading_still_replaces_the_list(self):
        body = "Part of #5\n\nScenarios:  \n\n- `Old`\n- `Older`\n\nNotes\n"
        gh = FakeGh([sub(8, body=body)])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, ["New"])
        self.assertEqual(gh.subs[8]["body"], "Part of #5\n\nScenarios:\n- `New`\n\nNotes\n")

    def test_a_later_list_after_a_blank_line_is_kept(self):
        body = "Scenarios:\n- `a`\n\n- [ ] follow-up\n"
        gh = FakeGh([sub(8, body=body)])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, ["b"])
        self.assertEqual(gh.subs[8]["body"], "Scenarios:\n- `b`\n\n- [ ] follow-up\n")
        needs_spec.clear(5, 8, [])
        self.assertEqual(gh.subs[8]["body"], "- [ ] follow-up\n")

    def test_given_no_scenarios_then_a_bare_heading_is_removed(self):
        gh = FakeGh([sub(8, body="Part of #5\n\nScenarios:\n")])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, [])
        self.assertEqual(gh.subs[8]["body"], "Part of #5\n")

    def test_given_the_body_did_not_land_then_the_read_back_exits_non_zero(self):
        # Given a stale list, and a gh that removes the label but loses the body write
        gh = FakeGh([sub(8, labels=(LABEL,), body="x\n\nScenarios:\n- `Old`\n")], body_drops=True)
        needs_spec.run_gh = gh
        # Then the read-back sees the old list and exits non-zero
        with self.assertRaises(SystemExit) as ctx:
            needs_spec.clear(5, 8, ["New"])
        self.assertIn("#8", str(ctx.exception.code))

    def test_given_the_label_is_gone_and_no_scenarios_then_nothing_is_edited(self):
        gh = FakeGh([sub(8)])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, [])
        self.assertFalse(any(a[:2] == ["issue", "edit"] for a, _ in gh.calls))

    def test_given_no_scenarios_then_only_the_label_is_removed(self):
        gh = FakeGh([sub(8, labels=("sdd:task", LABEL), body="Part of #5 → x\n")])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, [])
        self.assertEqual(gh.subs[8]["labels"], ["sdd:task"])
        self.assertEqual(gh.subs[8]["body"], "Part of #5 → x\n")
        edit = next(a for a, _ in gh.calls if a[:2] == ["issue", "edit"])
        self.assertNotIn("--body-file", edit)

    def test_the_body_is_sent_via_stdin(self):
        gh = FakeGh([sub(8, labels=(LABEL,))])
        needs_spec.run_gh = gh
        needs_spec.clear(5, 8, ["A"])
        args, stdin = next((a, s) for a, s in gh.calls if a[:2] == ["issue", "edit"])
        self.assertEqual(args[args.index("--body-file") + 1], "-")
        self.assertIn("- `A`", stdin)

    def test_blank_scenario_is_refused_before_any_gh_call(self):
        gh = FakeGh([sub(8, labels=(LABEL,))])
        needs_spec.run_gh = gh
        with self.assertRaises(SystemExit):
            needs_spec.clear(5, 8, ["ok", "  "])
        self.assertEqual(gh.calls, [])

    def test_given_a_child_that_is_not_an_open_sub_issue_then_it_exits_non_zero(self):
        gh = FakeGh([sub(8), sub(9, state="CLOSED", labels=(LABEL,))])
        needs_spec.run_gh = gh
        for child in (9, 99):
            with self.assertRaises(SystemExit) as ctx:
                needs_spec.clear(5, child, ["A"])
            self.assertIn(f"#{child}", str(ctx.exception.code))
        self.assertFalse(any(a[:2] == ["issue", "edit"] for a, _ in gh.calls))

    def test_given_the_edit_did_not_land_then_the_read_back_exits_non_zero(self):
        gh = FakeGh([sub(8, labels=(LABEL,))], edit_drops=True)
        needs_spec.run_gh = gh
        with self.assertRaises(SystemExit) as ctx:
            needs_spec.clear(5, 8, ["A"])
        self.assertIn("#8", str(ctx.exception.code))
        self.assertIn("again", str(ctx.exception.code))

    def test_main_clears_with_every_scenario_flag(self):
        gh = FakeGh([sub(8, labels=(LABEL,))])
        needs_spec.run_gh = gh
        with contextlib.redirect_stdout(io.StringIO()):
            needs_spec.main(["5", "--clear", "8", "--scenario", "A", "--scenario", "B"])
        self.assertEqual(gh.subs[8]["labels"], [])
        self.assertIn("- `A`\n- `B`", gh.subs[8]["body"])

    def test_scenario_without_clear_is_refused(self):
        needs_spec.run_gh = FakeGh([])
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                needs_spec.main(["5", "--scenario", "A"])


if __name__ == "__main__":
    unittest.main()
