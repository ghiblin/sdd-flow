"""Stdlib tests for set-stage.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import importlib.util
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "set_stage", pathlib.Path(__file__).with_name("set-stage.py")
)
set_stage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_stage)

BODY = (
    "Preamble — kept → as is, Niccolò\n"
    "<!-- sdd:begin -->\n"
    "**Intent:** Add a router — with arrows → and Niccolò\n"
    "**Stage:** drafting-spec\n"
    "**Worktree:** .claude/worktrees/add-router\n"
    "**Branch:** sdd/5-add-router\n"
    "**Spec files:** docs/specs/crates/dietpal-agent.md\n"
    "## Open decisions\n"
    "- [ ] _none_\n"
    "<!-- sdd:end -->\n"
)


class FakeGh:
    """Plays GitHub's side of one issue's body and labels."""

    def __init__(self, body=BODY, labels=("sdd:feature", "sdd:stage:spec-approved"),
                 corrupt_on_read=False, ignore_label_edit=False):
        self.body = body
        self.labels = list(labels)
        self.corrupt_on_read = corrupt_on_read
        self.ignore_label_edit = ignore_label_edit
        self.calls = []
        self.reads = 0

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "view"]:
            self.reads += 1
            body = self.body
            if self.corrupt_on_read and self.reads > 1:
                body = body.replace("—", "â€”")
            return json.dumps({"body": body, "labels": [{"name": n} for n in self.labels]})
        if args[:2] == ["issue", "edit"]:
            if "--body-file" in args:
                self.body = stdin
            if not self.ignore_label_edit:
                for i, a in enumerate(args):
                    if a == "--remove-label":
                        self.labels = [l for l in self.labels if l not in args[i + 1].split(",")]
                for i, a in enumerate(args):
                    if a == "--add-label":
                        self.labels += args[i + 1].split(",")
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


class SetStage(unittest.TestCase):
    def run_script(self, gh, stage="implementing", n=5):
        set_stage.run_gh = gh
        set_stage.set_stage(n, stage)

    def test_given_drafting_when_set_to_implementing_then_label_is_swapped(self):
        gh = FakeGh()
        self.run_script(gh)
        self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:implementing"])

    def test_given_drafting_when_set_to_implementing_then_only_the_stage_line_changes(self):
        gh = FakeGh()
        self.run_script(gh)
        self.assertEqual(
            gh.body, BODY.replace("**Stage:** drafting-spec", "**Stage:** implementing")
        )

    def test_any_prior_stage_label_is_removed(self):
        gh = FakeGh(labels=["sdd:feature", "sdd:stage:implementing", "sdd:stage:complete"])
        self.run_script(gh, stage="verified")
        self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:verified"])

    def test_body_is_sent_as_utf8_text_via_stdin(self):
        gh = FakeGh()
        self.run_script(gh)
        writes = [(a, s) for a, s in gh.calls if "--body-file" in a]
        self.assertEqual(len(writes), 1)
        args, stdin = writes[0]
        self.assertEqual(args[args.index("--body-file") + 1], "-")
        self.assertIn("Niccolò", stdin)

    def test_unknown_stage_is_refused_before_any_write(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, stage="done")
        self.assertFalse([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]])

    def test_empty_body_is_refused(self):
        gh = FakeGh(body="  \n")
        with self.assertRaises(SystemExit):
            self.run_script(gh)
        self.assertFalse([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]])

    def test_body_without_a_stage_line_is_refused(self):
        gh = FakeGh(body="<!-- sdd:begin -->\n**Intent:** x\n<!-- sdd:end -->\n")
        with self.assertRaises(SystemExit):
            self.run_script(gh)
        self.assertFalse([a for a, _ in gh.calls if "--body-file" in a])

    def test_given_the_read_back_differs_then_it_exits_non_zero(self):
        gh = FakeGh(corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_given_the_label_did_not_change_then_it_exits_non_zero(self):
        gh = FakeGh(ignore_label_edit=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh)
        self.assertNotEqual(ctx.exception.code, 0)

    def test_main_takes_issue_and_stage(self):
        gh = FakeGh()
        set_stage.run_gh = gh
        set_stage.main(["5", "complete"])
        self.assertIn("sdd:stage:complete", gh.labels)
        self.assertIn("**Stage:** complete\n", gh.body)
        self.assertTrue(all(a[2] == "5" for a, _ in gh.calls))

    def test_the_body_is_written_before_the_label_is_swapped(self):
        gh = FakeGh()
        self.run_script(gh)
        edits = [a for a, _ in gh.calls if a[:2] == ["issue", "edit"]]
        self.assertIn("--body-file", edits[0])
        self.assertIn("--add-label", edits[-1])

    def test_given_the_labels_already_match_then_no_label_edit_happens(self):
        body = BODY.replace("**Stage:** drafting-spec", "**Stage:** complete")
        gh = FakeGh(body=body, labels=["sdd:feature", "sdd:stage:implementing"])
        self.run_script(gh)
        edits = [a for a, _ in gh.calls if a[:2] == ["issue", "edit"]]
        self.assertEqual(len(edits), 1)
        self.assertNotIn("--add-label", edits[0])

    def test_given_the_body_write_fails_then_the_label_is_not_swapped(self):
        gh = FakeGh()

        def failing(args, stdin=None):
            if "--body-file" in args:
                raise SystemExit("gh issue edit failed (1)")
            return gh(args, stdin)

        set_stage.run_gh = failing
        with self.assertRaises(SystemExit):
            set_stage.set_stage(5, "implementing")
        self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:spec-approved"])

    def test_given_a_crlf_body_already_at_the_stage_then_no_write_happens(self):
        body = BODY.replace("**Stage:** drafting-spec", "**Stage:** implementing").replace("\n", "\r\n")
        gh = FakeGh(body=body, labels=["sdd:feature", "sdd:stage:implementing"])
        self.run_script(gh)
        self.assertEqual([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]], [])

    def test_given_a_crlf_body_then_the_stage_line_changes_and_the_body_is_written_as_lf(self):
        gh = FakeGh(body=BODY.replace("\n", "\r\n"))
        self.run_script(gh)
        self.assertEqual(gh.body, BODY.replace("**Stage:** drafting-spec", "**Stage:** implementing"))


def with_decisions(*lines):
    return BODY.replace("- [ ] _none_\n", "".join(line + "\n" for line in lines))


NO_APPROVAL_LINE = (
    "issue #5: no `Approve the spec section? (draft <k>)` line in the `## Open decisions` block "
    "(the block ends at the next heading or `<!-- sdd:end -->`)"
)


def edits_of(gh):
    return [a for a, _ in gh.calls if a[:2] == ["issue", "edit"]]


class SpecApprovedGate(unittest.TestCase):
    Q = "Approve the spec section? (draft {k})"

    def attempt(self, body, labels=("sdd:feature", "sdd:stage:drafting-spec"), stage="spec-approved"):
        gh = FakeGh(body=body, labels=labels)
        set_stage.run_gh = gh
        set_stage.set_stage(5, stage)
        return gh

    def refused(self, body, labels=("sdd:feature", "sdd:stage:drafting-spec"), stage="spec-approved"):
        gh = FakeGh(body=body, labels=labels)
        set_stage.run_gh = gh
        with self.assertRaises(SystemExit) as ctx:
            set_stage.set_stage(5, stage)
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertEqual(edits_of(gh), [])
        return str(ctx.exception.code)

    def test_spec_approved_needs_approval(self):
        q = self.Q
        self.refused(with_decisions("- [ ] " + q.format(k=1)))
        self.refused(with_decisions("- [x] " + q.format(k=1) + " → no"))
        self.refused(with_decisions("- [x] " + q.format(k=1) + " → approved", "- [ ] " + q.format(k=2)))
        self.refused(with_decisions("- [x] " + q.format(k=1) + " → approved", "- [x] " + q.format(k=2) + " → request changes"))
        self.refused(with_decisions("- [x] " + q.format(k=2) + " → approved", "- [x] " + q.format(k=1) + " → approved", "- [ ] " + q.format(k=10)))

    def test_spec_approved_sets_label(self):
        q = self.Q
        for resolution in ("yes", "approved", " Approved. ", "YES"):
            gh = self.attempt(with_decisions("- [x] " + q.format(k=1) + " → no", "- [x] " + q.format(k=2) + " → " + resolution))
            self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:spec-approved"])
            self.assertIn("**Stage:** spec-approved\n", gh.body)

    def test_no_approval_line_message(self):
        message = self.refused(BODY)
        self.assertEqual(message, NO_APPROVAL_LINE)

    def test_implementing_refused_outside_approved(self):
        for labels in (["sdd:feature", "sdd:stage:drafting-spec"], ["sdd:feature", "sdd:stage:intent"], ["sdd:feature"]):
            self.refused(BODY, labels=labels, stage="implementing")

    def test_implementing_allowed_from_approved(self):
        for label in ("spec-approved", "implementing", "complete"):
            gh = self.attempt(BODY, labels=["sdd:feature", "sdd:stage:" + label], stage="implementing")
            self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:implementing"])

    def test_drafting_spec_allowed_from_any_label(self):
        gh = self.attempt(BODY, labels=["sdd:feature", "sdd:stage:complete"], stage="drafting-spec")
        self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:drafting-spec"])

    def test_approval_line_outside_open_decisions_is_ignored(self):
        q = self.Q
        body = with_decisions("- [ ] " + q.format(k=1)).replace(
            "Preamble", "- [x] " + q.format(k=9) + " → yes\nPreamble")
        self.refused(body)
        quoted = BODY.replace("Preamble", "- [x] " + q.format(k=1) + " → yes\nPreamble")
        self.assertEqual(self.refused(quoted), NO_APPROVAL_LINE)

    def test_spec_approved_rerun_is_a_no_op(self):
        q = self.Q
        body = with_decisions("- [x] " + q.format(k=1) + " → approved").replace(
            "**Stage:** drafting-spec", "**Stage:** spec-approved")
        gh = self.attempt(body, labels=["sdd:feature", "sdd:stage:spec-approved"])
        self.assertEqual(sorted(gh.labels), ["sdd:feature", "sdd:stage:spec-approved"])
        self.assertEqual(edits_of(gh), [])

    def test_approval_line_after_a_gap_counts(self):
        q = self.Q
        body = with_decisions("- [x] " + q.format(k=1) + " → approved", "", "A note.", "- [ ] " + q.format(k=2))
        self.assertEqual(self.refused(body), "issue #5: the spec section is not approved")
        approved = with_decisions("- [ ] " + q.format(k=1), "", "A note.", "- [x] " + q.format(k=2) + " → yes")
        self.assertEqual(sorted(self.attempt(approved).labels), ["sdd:feature", "sdd:stage:spec-approved"])

    def test_block_ends_at_the_end_marker_or_any_heading(self):
        q = self.Q
        for end in ("<!-- sdd:end -->", "##", "##\tNotes", "### Notes"):
            with self.subTest(end=end):
                body = with_decisions("- [ ] " + q.format(k=1), end, "- [x] " + q.format(k=9) + " → yes")
                self.assertEqual(self.refused(body), "issue #5: the spec section is not approved")
        cut = with_decisions("### Notes", "- [x] " + q.format(k=1) + " → yes")
        self.assertEqual(self.refused(cut), NO_APPROVAL_LINE)

    def test_spec_approved_refused_from_another_label(self):
        q = self.Q
        message = self.refused(with_decisions("- [x] " + q.format(k=1) + " → approved"), labels=["sdd:feature", "sdd:stage:implementing"])
        self.assertEqual(message, "issue #5: spec-approved is allowed only from drafting-spec or spec-approved")


if __name__ == "__main__":
    unittest.main()
