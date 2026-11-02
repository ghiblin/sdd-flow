"""Stdlib tests for check-open-decision.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-reconcile/scripts -v
"""
import importlib.util
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "check_open_decision", pathlib.Path(__file__).with_name("check-open-decision.py")
)
check_open_decision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_open_decision)

HEAD = (
    "<!-- sdd:begin -->\n"
    "**Intent:** Add a router — with arrows → and Niccolò\n"
    "**Stage:** implementing\n"
    "**Spec files:** docs/specs/crates/dietpal-agent.md\n"
    "## Open decisions\n"
)
TAIL = "<!-- sdd:end -->\n"
Q = "Which trait shape — A or B?"
OPEN = HEAD + "- [x] Old choice (user, 2026-10-01)\n" + f"- [ ] {Q}\n" + "- [ ] Other?\n" + TAIL


class FakeGh:
    def __init__(self, body=OPEN, corrupt_on_read=False):
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


class CheckOpenDecision(unittest.TestCase):
    def run_script(self, gh, question=Q, resolved_as=None):
        check_open_decision.run_gh = gh
        check_open_decision.check_open_decision(5, question, resolved_as)

    def test_given_an_open_question_then_only_its_box_is_checked(self):
        gh = FakeGh()
        self.run_script(gh)
        self.assertEqual(
            gh.body,
            HEAD + "- [x] Old choice (user, 2026-10-01)\n" + f"- [x] {Q}\n" + "- [ ] Other?\n" + TAIL,
        )

    def test_given_resolved_as_then_the_checked_line_carries_that_text(self):
        gh = FakeGh()
        self.run_script(gh, resolved_as="Trait shape: A (user, 2026-10-13)")
        self.assertIn(f"- [x] {Q} → Trait shape: A (user, 2026-10-13)\n- [ ] Other?\n", gh.body)
        self.assertNotIn(f"- [ ] {Q}", gh.body)

    def test_given_the_question_after_a_gap_then_only_its_box_is_checked(self):
        body = HEAD + "- [x] Old choice (user, 2026-10-01)\n\nA note.\n" + f"- [ ] {Q}\n" + TAIL + "## Later\n"
        gh = FakeGh(body=body)
        self.run_script(gh, resolved_as="A (user, 2026-10-26)")
        self.assertEqual(gh.body, body.replace(f"- [ ] {Q}\n", f"- [x] {Q} → A (user, 2026-10-26)\n"))

    def test_given_the_question_only_after_the_end_marker_then_it_exits_non_zero(self):
        gh = FakeGh(body=HEAD + "- [x] Old choice (user, 2026-10-01)\n" + TAIL + f"- [ ] {Q}\n")
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertIn("no open decision", str(ctx.exception.code))
        self.assertEqual(gh.edits(), [])

    def test_given_the_question_is_already_checked_then_no_write_happens(self):
        gh = FakeGh(body=HEAD + f"- [x] {Q}\n" + TAIL)
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_given_the_question_is_not_in_the_block_then_it_exits_non_zero(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh, question="Never asked?")
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(gh.edits(), [])

    def test_a_matching_line_outside_the_block_is_ignored(self):
        gh = FakeGh(body=f"- [ ] {Q}\n" + HEAD + "- [ ] Other?\n" + TAIL)
        with self.assertRaises(SystemExit):
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

    def test_multi_line_resolution_is_refused_before_any_gh_call(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, resolved_as="a\nb")
        self.assertEqual(gh.calls, [])

    def test_empty_body_is_refused(self):
        gh = FakeGh(body="")
        with self.assertRaises(SystemExit):
            self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_given_the_read_back_differs_then_it_exits_non_zero(self):
        gh = FakeGh(corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_given_resolved_earlier_in_other_words_then_a_rerun_is_a_no_op(self):
        gh = FakeGh(body=HEAD + f"- [x] {Q} → Trait shape: A (user, 2026-10-01)\n" + TAIL)
        self.run_script(gh, resolved_as="Trait shape: A (user)")
        self.assertEqual(gh.edits(), [])

    def test_a_line_equal_to_the_resolution_does_not_stand_in_for_the_question(self):
        # The block has no line for "Retry policy?" at all; only an unrelated checked
        # line whose text equals the resolution. That must not count as resolved.
        gh = FakeGh(body=HEAD + "- [x] Trait shape: A (user)\n- [ ] Cache TTL?\n" + TAIL)
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="Retry policy?", resolved_as="Trait shape: A (user)")
        self.assertEqual(gh.edits(), [])

    def test_an_existing_open_question_containing_the_separator_can_still_be_checked_off(self):
        gh = FakeGh(body=HEAD + "- [ ] Store X → Y?\n" + TAIL)
        self.run_script(gh, question="Store X → Y?", resolved_as="yes")
        self.assertEqual(gh.body, HEAD + "- [x] Store X -> Y? → yes\n" + TAIL)

    def test_a_checked_off_arrow_question_is_found_again_by_its_original_text(self):
        gh = FakeGh(body=HEAD + "- [ ] Store X → Y?\n" + TAIL)
        self.run_script(gh, question="Store X → Y?")
        self.assertEqual(gh.body, HEAD + "- [x] Store X -> Y?\n" + TAIL)
        self.run_script(gh, question="Store X → Y?")
        self.assertEqual(len(gh.edits()), 1)

    def test_an_old_format_raw_arrow_resolved_line_is_still_a_no_op(self):
        gh = FakeGh(body=HEAD + "- [x] Store X → Y? → yes\n" + TAIL)
        self.run_script(gh, question="Store X → Y?")
        self.assertEqual(gh.edits(), [])

    def test_a_checked_off_arrow_question_does_not_resolve_its_prefix(self):
        gh = FakeGh(body=HEAD + "- [ ] Store X → Y?\n" + TAIL)
        self.run_script(gh, question="Store X → Y?")
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="Store X")

    def test_given_the_question_both_checked_and_open_then_the_open_copy_is_checked(self):
        gh = FakeGh(body=HEAD + f"- [x] {Q} → A\n- [ ] {Q}\n" + TAIL)
        self.run_script(gh, resolved_as="B")
        self.assertEqual(gh.body, HEAD + f"- [x] {Q} → A\n- [x] {Q} → B\n" + TAIL)

    def test_a_checked_line_with_a_blank_resolution_still_matches_its_question(self):
        gh = FakeGh(body=HEAD + f"- [x] {Q} → \n" + TAIL)
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_the_none_placeholder_is_never_checked_off(self):
        gh = FakeGh(body=HEAD + "- [ ] _none_\n" + TAIL)
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="_none_")
        self.assertEqual(gh.edits(), [])

    def test_trailing_whitespace_on_the_open_line_still_matches(self):
        gh = FakeGh(body=HEAD + f"- [ ] {Q}  \n" + TAIL)
        self.run_script(gh)
        self.assertEqual(gh.body, HEAD + f"- [x] {Q}\n" + TAIL)

    def test_a_box_without_the_usual_spacing_still_matches(self):
        gh = FakeGh(body=HEAD + f"- [ ]{Q}\n" + TAIL)
        self.run_script(gh)
        self.assertEqual(gh.body, HEAD + f"- [x] {Q}\n" + TAIL)

    def test_given_only_the_none_placeholder_then_an_unknown_question_exits_non_zero(self):
        gh = FakeGh(body=HEAD + "- [ ] _none_\n" + TAIL)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh, question="Cache TTL?")
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(gh.edits(), [])

    def test_given_nothing_open_then_an_unknown_question_exits_non_zero(self):
        gh = FakeGh(body=HEAD + "- [x] Trait shape: A (user)\n" + TAIL)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh, resolved_as="Trait shape: A (user, again)")
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(gh.edits(), [])

    def test_a_resolved_question_that_merely_starts_with_the_question_does_not_count(self):
        gh = FakeGh(body=HEAD + "- [x] Use Redis for sessions? yes\n" + TAIL)
        with self.assertRaises(SystemExit):
            self.run_script(gh, question="Use Redis?")
        self.assertEqual(gh.edits(), [])

    def test_an_uppercase_x_counts_as_checked(self):
        gh = FakeGh(body=HEAD + f"- [X] {Q}\n" + TAIL)
        self.run_script(gh)
        self.assertEqual(gh.edits(), [])

    def test_given_a_blank_line_after_the_heading_then_the_question_is_checked(self):
        gh = FakeGh(body=HEAD + f"\n- [ ] {Q}\n" + TAIL)
        self.run_script(gh)
        self.assertEqual(gh.body, HEAD + f"\n- [x] {Q}\n" + TAIL)

    def test_given_a_crlf_body_then_the_question_is_checked(self):
        gh = FakeGh(body=OPEN.replace("\n", "\r\n"))
        self.run_script(gh)
        self.assertIn(f"- [x] {Q}\n- [ ] Other?\n", gh.body)

    def test_main_takes_issue_question_and_optional_resolution(self):
        gh = FakeGh()
        check_open_decision.run_gh = gh
        check_open_decision.main(["5", "--question", "Other?", "--resolved-as", "Other: no"])
        self.assertIn("- [x] Other? → Other: no\n" + TAIL, gh.body)


if __name__ == "__main__":
    unittest.main()
