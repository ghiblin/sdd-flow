"""Stdlib tests for add-open-decision.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import importlib.util
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "add_open_decision", pathlib.Path(__file__).with_name("add-open-decision.py")
)
add_open_decision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_open_decision)

HEAD = (
    "<!-- sdd:begin -->\n"
    "**Intent:** Add a router — with arrows → and Niccolò\n"
    "**Stage:** implementing\n"
    "**Spec files:** docs/specs/crates/dietpal-agent.md\n"
    "## Open decisions\n"
)
EMPTY = HEAD + "- [ ] _none_\n<!-- sdd:end -->\n"
ONE = HEAD + "- [x] Old choice (user, 2026-10-01)\n<!-- sdd:end -->\n"


class FakeGh:
    def __init__(self, body=EMPTY, corrupt_on_read=False):
        self.body = body
        self.corrupt_on_read = corrupt_on_read
        self.calls = []
        self.reads = 0

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "view"]:
            self.reads += 1
            body = self.body
            if self.corrupt_on_read and self.reads > 1:
                body = body.replace("→", "â†’")
            return json.dumps({"body": body})
        if args[:2] == ["issue", "edit"]:
            self.body = stdin
            return ""
        raise AssertionError(f"unexpected gh call: {args}")

    def edits(self):
        return [s for a, s in self.calls if a[:2] == ["issue", "edit"]]


class AddOpenDecision(unittest.TestCase):
    def run_script(self, gh, question="Which trait shape — A or B?"):
        add_open_decision.run_gh = gh
        add_open_decision.add_open_decision(5, question)

    def test_given_the_none_placeholder_then_it_is_replaced_by_the_question(self):
        gh = FakeGh()
        self.run_script(gh)
        self.assertEqual(
            gh.body, HEAD + "- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n"
        )

    def test_given_existing_decisions_then_the_question_is_appended_inside_the_block(self):
        gh = FakeGh(body=ONE)
        self.run_script(gh)
        self.assertEqual(
            gh.body,
            HEAD
            + "- [x] Old choice (user, 2026-10-01)\n"
            + "- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n",
        )

    def test_given_the_same_question_after_a_gap_then_no_write_happens(self):
        gh = FakeGh(body=HEAD + "- [x] Old choice (user, 2026-10-01)\n\nA note.\n- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_given_the_same_question_after_a_heading_then_it_is_added(self):
        body = HEAD + "- [x] Old choice (user, 2026-10-01)\n### Notes\n- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n"
        gh = FakeGh(body=body)
        self.run_script(gh)
        self.assertEqual(len(gh.edits()), 1)

    def test_given_the_same_question_is_already_open_then_no_write_happens(self):
        gh = FakeGh(body=HEAD + "- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_body_is_sent_as_utf8_text_via_stdin(self):
        gh = FakeGh()
        self.run_script(gh)
        (args, stdin), = [(a, s) for a, s in gh.calls if a[:2] == ["issue", "edit"]]
        self.assertEqual(args[args.index("--body-file") + 1], "-")
        self.assertIn("Niccolò", stdin)

    def test_empty_question_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, question=" ")
        self.assertEqual(gh.calls, [])

    def test_multi_line_question_is_refused(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="a\nb")
        self.assertEqual(gh.calls, [])

    def test_empty_body_is_refused(self):
        gh = FakeGh(body="")
        with self.assertRaises(SystemExit):
            self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_body_without_an_open_decisions_block_is_refused(self):
        gh = FakeGh(body="<!-- sdd:begin -->\n**Stage:** implementing\n<!-- sdd:end -->\n")
        with self.assertRaises(SystemExit):
            self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_given_the_read_back_differs_then_it_exits_non_zero(self):
        gh = FakeGh(corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_given_the_same_question_was_already_resolved_then_it_is_not_reopened(self):
        gh = FakeGh(body=HEAD + "- [x] Which trait shape — A or B? → A (user)\n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_given_a_blank_line_after_the_heading_then_the_placeholder_is_still_replaced(self):
        gh = FakeGh(body=HEAD + "\n- [ ] _none_\n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(
            gh.body, HEAD + "\n- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n"
        )

    def test_given_a_crlf_body_then_the_block_is_found_and_edited(self):
        gh = FakeGh(body=EMPTY.replace("\n", "\r\n"))
        self.run_script(gh)
        self.assertEqual(
            gh.body, HEAD + "- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n"
        )

    def test_a_resolved_question_that_merely_starts_with_the_question_does_not_block_adding(self):
        gh = FakeGh(body=HEAD + "- [x] Use Redis for sessions? yes\n<!-- sdd:end -->\n")
        self.run_script(gh, question="Use Redis?")
        self.assertIn("- [x] Use Redis for sessions? yes\n- [ ] Use Redis?\n", gh.body)

    def test_given_the_question_was_checked_with_an_uppercase_x_then_it_is_not_reopened(self):
        gh = FakeGh(body=HEAD + "- [X] Which trait shape — A or B?\n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_trailing_whitespace_on_an_existing_line_still_counts_as_the_same_question(self):
        gh = FakeGh(body=HEAD + "- [ ] Which trait shape — A or B? \n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_the_none_placeholder_cannot_be_added_as_a_question(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="_none_")
        self.assertEqual(gh.calls, [])

    def test_a_question_containing_the_resolution_separator_is_refused(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="Store X → Y?")
        self.assertEqual(gh.calls, [])

    def test_a_question_containing_a_bare_arrow_is_refused(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="Store X →")
        self.assertEqual(gh.calls, [])

    def test_a_placeholder_with_trailing_whitespace_is_still_replaced(self):
        gh = FakeGh(body=HEAD + "- [ ] _none_ \n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(gh.body, HEAD + "- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n")

    def test_a_checked_none_line_is_left_alone(self):
        gh = FakeGh(body=HEAD + "- [x] _none_\n<!-- sdd:end -->\n")
        self.run_script(gh)
        self.assertEqual(
            gh.body, HEAD + "- [x] _none_\n- [ ] Which trait shape — A or B?\n<!-- sdd:end -->\n"
        )

    def test_main_takes_issue_and_question(self):
        gh = FakeGh()
        add_open_decision.run_gh = gh
        add_open_decision.main(["5", "--question", "Q?"])
        self.assertIn("## Open decisions\n- [ ] Q?\n<!-- sdd:end -->", gh.body)


if __name__ == "__main__":
    unittest.main()
