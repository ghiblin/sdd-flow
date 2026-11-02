"""Stdlib tests for set-spec-files.py; `gh` is faked, GitHub is never reached.

Run: python3 -m unittest discover -s .claude/skills/sdd-reconcile/scripts -v
"""
import importlib.util
import json
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "set_spec_files", pathlib.Path(__file__).with_name("set-spec-files.py")
)
set_spec_files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_spec_files)

BODY = (
    "<!-- sdd:begin -->\n"
    "**Intent:** Add a router — with arrows → and Niccolò\n"
    "**Stage:** implementing\n"
    "**Worktree:** .claude/worktrees/add-router\n"
    "**Branch:** sdd/5-add-router\n"
    "**Spec files:** docs/specs/crates/dietpal-agent.md\n"
    "## Open decisions\n"
    "- [ ] _none_\n"
    "<!-- sdd:end -->\n"
)


class FakeGh:
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
                body = body.replace("→", "â†’")
            return json.dumps({"body": body})
        if args[:2] == ["issue", "edit"]:
            self.body = stdin
            return ""
        raise AssertionError(f"unexpected gh call: {args}")


class SetSpecFiles(unittest.TestCase):
    def run_script(self, gh, files, add=False):
        set_spec_files.run_gh = gh
        set_spec_files.set_spec_files(5, files, add=add)

    def test_given_new_files_when_set_then_the_line_lists_exactly_them(self):
        gh = FakeGh()
        self.run_script(gh, ["docs/specs/server/chat-api.md", "docs/specs/domain/patient.md"])
        self.assertEqual(
            gh.body,
            BODY.replace(
                "**Spec files:** docs/specs/crates/dietpal-agent.md",
                "**Spec files:** docs/specs/server/chat-api.md, docs/specs/domain/patient.md",
            ),
        )

    def test_given_add_mode_then_new_files_are_appended_without_duplicates(self):
        gh = FakeGh()
        self.run_script(
            gh, ["docs/specs/crates/dietpal-agent.md", "docs/specs/server/chat-api.md"], add=True
        )
        self.assertIn(
            "**Spec files:** docs/specs/crates/dietpal-agent.md, docs/specs/server/chat-api.md\n",
            gh.body,
        )

    def test_given_nothing_changes_then_no_write_happens(self):
        gh = FakeGh()
        self.run_script(gh, ["docs/specs/crates/dietpal-agent.md"], add=True)
        self.assertFalse([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]])

    def test_body_is_sent_as_utf8_text_via_stdin(self):
        gh = FakeGh()
        self.run_script(gh, ["a.md"])
        (args, stdin), = [(a, s) for a, s in gh.calls if a[:2] == ["issue", "edit"]]
        self.assertEqual(args[args.index("--body-file") + 1], "-")
        self.assertIn("Niccolò", stdin)

    def test_empty_file_list_is_refused(self):
        gh = FakeGh()
        with self.assertRaises(SystemExit):
            self.run_script(gh, [])
        self.assertEqual(gh.calls, [])

    def test_empty_body_is_refused(self):
        gh = FakeGh(body="")
        with self.assertRaises(SystemExit):
            self.run_script(gh, ["a.md"])
        self.assertFalse([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]])

    def test_body_without_a_spec_files_line_is_refused(self):
        gh = FakeGh(body="<!-- sdd:begin -->\n**Stage:** implementing\n<!-- sdd:end -->\n")
        with self.assertRaises(SystemExit):
            self.run_script(gh, ["a.md"])
        self.assertFalse([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]])

    def test_given_the_read_back_differs_then_it_exits_non_zero(self):
        gh = FakeGh(corrupt_on_read=True)
        with self.assertRaises(SystemExit) as ctx:
            self.run_script(gh, ["a.md"])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_main_takes_issue_and_repeated_spec_file(self):
        gh = FakeGh()
        set_spec_files.run_gh = gh
        set_spec_files.main(["5", "--add", "--spec-file", "b.md", "--spec-file", "c.md"])
        self.assertIn(
            "**Spec files:** docs/specs/crates/dietpal-agent.md, b.md, c.md\n", gh.body
        )

    def test_given_a_crlf_body_with_the_same_files_then_no_write_happens(self):
        gh = FakeGh(body=BODY.replace("\n", "\r\n"))
        self.run_script(gh, ["docs/specs/crates/dietpal-agent.md"])
        self.assertEqual([a for a, _ in gh.calls if a[:2] == ["issue", "edit"]], [])

    def test_given_a_crlf_body_then_the_line_is_rewritten_and_the_body_written_as_lf(self):
        gh = FakeGh(body=BODY.replace("\n", "\r\n"))
        self.run_script(gh, ["docs/specs/server/chat-api.md"])
        self.assertEqual(
            gh.body,
            BODY.replace("docs/specs/crates/dietpal-agent.md", "docs/specs/server/chat-api.md"),
        )


if __name__ == "__main__":
    unittest.main()
