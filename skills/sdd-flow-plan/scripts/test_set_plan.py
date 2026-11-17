"""Stdlib tests for set-plan.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s skills/sdd-flow-plan/scripts -v
"""
import importlib.util
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "set_plan", pathlib.Path(__file__).with_name("set-plan.py")
)
set_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_plan)

BODY = (
    "<!-- sdd:begin -->\n"
    "**Intent:** Add a router\n"
    "**Stage:** planning\n"
    "**Spec files:** docs/specs/agent.md\n"
    "## Plan\n"
    "_not yet planned_\n"
    "## Open decisions\n"
    "- [ ] _none_\n"
    "<!-- sdd:end -->\n"
)


class FakeGh:
    """Plays GitHub's side of one issue's body."""

    def __init__(self, body=BODY, corrupt_on_read=False):
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
                body = body.replace("—", "â€”")
            return json.dumps({"body": body})
        if args[:2] == ["issue", "edit"]:
            if "--body-file" in args:
                self.body = stdin
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


def edits_of(gh):
    return [a for a, _ in gh.calls if a[:2] == ["issue", "edit"]]


class SetPlan(unittest.TestCase):
    def run_script(self, gh, content, n=5):
        set_plan.run_gh = gh
        set_plan.set_plan(n, content)

    def test_plan_content_replaces_the_placeholder(self):
        gh = FakeGh()
        self.run_script(gh, "Approach: use a router.\n\n**Components:** agent, server.")
        self.assertEqual(
            gh.body,
            BODY.replace(
                "## Plan\n_not yet planned_\n",
                "## Plan\nApproach: use a router.\n\n**Components:** agent, server.\n",
            ),
        )

    def test_internal_h3_subheadings_do_not_end_the_block_early(self):
        gh = FakeGh()
        content = "### Approach\nUse a router.\n\n### Trade-offs\nSimpler, slower fan-out."
        self.run_script(gh, content)
        self.assertIn(content, gh.body)
        self.assertIn("## Open decisions\n- [ ] _none_\n", gh.body)

    def test_block_ends_at_a_single_hash_heading_too(self):
        body = BODY.replace("## Open decisions", "# Notes\nstray text\n## Open decisions")
        gh = FakeGh(body=body)
        self.run_script(gh, "New content.")
        self.assertIn("## Plan\nNew content.\n# Notes\n", gh.body)

    def test_no_op_when_content_already_matches(self):
        gh = FakeGh()
        self.run_script(gh, "_not yet planned_")
        self.assertEqual(edits_of(gh), [])

    def test_empty_content_leaves_no_blank_artifact(self):
        gh = FakeGh()
        self.run_script(gh, "")
        self.assertIn("## Plan\n## Open decisions", gh.body)

    def test_missing_plan_heading_is_refused(self):
        gh = FakeGh(body=BODY.replace("## Plan\n_not yet planned_\n", ""))
        with self.assertRaises(SystemExit):
            self.run_script(gh, "x")
        self.assertEqual(edits_of(gh), [])

    def test_duplicate_plan_heading_is_refused(self):
        gh = FakeGh(body=BODY + "## Plan\nsecond\n")
        with self.assertRaises(SystemExit):
            self.run_script(gh, "x")
        self.assertEqual(edits_of(gh), [])

    def test_empty_body_is_refused(self):
        gh = FakeGh(body="  \n")
        with self.assertRaises(SystemExit):
            self.run_script(gh, "x")
        self.assertEqual(edits_of(gh), [])

    def test_given_the_read_back_differs_then_it_exits_non_zero(self):
        gh = FakeGh(corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh, "New plan text with — an em dash.")
        self.assertNotEqual(ctx.exception.code, 0)

    def test_given_a_crlf_body_the_write_is_lf(self):
        gh = FakeGh(body=BODY.replace("\n", "\r\n"))
        self.run_script(gh, "New content.")
        self.assertEqual(gh.body, BODY.replace("## Plan\n_not yet planned_\n", "## Plan\nNew content.\n"))


class Cli(unittest.TestCase):
    def test_main_reads_body_file(self):
        import tempfile

        gh = FakeGh()
        set_plan.run_gh = gh
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "plan.md"
            path.write_text("From a file.", encoding="utf-8")
            set_plan.main(["5", "--body-file", str(path)])
        self.assertIn("## Plan\nFrom a file.\n", gh.body)


if __name__ == "__main__":
    unittest.main()
