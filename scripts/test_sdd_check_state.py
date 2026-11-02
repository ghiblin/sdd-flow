"""Stdlib unit tests for sdd_check_state. Run: python3 -m unittest scripts.test_sdd_check_state -v"""
import contextlib
import importlib.util
import io
import json
import pathlib
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "sdd_check_state", pathlib.Path(__file__).with_name("sdd_check_state.py")
)
sdd_check_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sdd_check_state)

BODY = "<!-- sdd:begin -->\n**Stage:** x\n**Branch:** sdd/7-demo\n<!-- sdd:end -->\n"


class Run(unittest.TestCase):
    """Calls main() with the gh, git and needs-spec helpers replaced by fakes."""

    def run_check(self, argv, labels=("sdd:stage:drafting-spec",), body=BODY,
                  needs_spec=(), child_state="CLOSED", branch="sdd/7-demo",
                  status="", main_sha="abc", gh_raw=None, gh_fail=False, issue_state="OPEN"):
        if body is BODY and labels:
            body = BODY.replace("**Stage:** x", "**Stage:** " + labels[0].split(":")[-1])
        issue = {"state": issue_state, "labels": [{"name": n} for n in labels], "body": body}

        def gh(args):
            if gh_fail:
                raise sdd_check_state.ToolError("gh failed")
            if gh_raw is not None:
                return gh_raw
            if args[2] == "9":
                return json.dumps({"state": child_state})
            return json.dumps(issue)

        def git(directory, *args):
            if args[0] == "branch":
                return branch
            if args[0] == "status":
                return status
            if args[0] == "rev-parse":
                return main_sha
            raise AssertionError(args)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sdd_check_state, "run_gh", gh), \
                mock.patch.object(sdd_check_state, "run_git", git), \
                mock.patch.object(sdd_check_state, "run_needs_spec", lambda n: list(needs_spec)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sdd_check_state.main(argv)
        return code, out.getvalue()

    def assert_fail(self, code, out):
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL", out)

    def assert_ok(self, code, out):
        self.assertEqual((code, out), (0, ""))


class Tests(Run):
    def test_label_count_fails(self):
        for labels in ((), ("sdd:stage:drafting-spec", "sdd:stage:implementing")):
            self.assert_fail(*self.run_check(["--issue", "7", "--stage", "intent"], labels=labels))

    def test_intent_leaves_drafting_spec(self):
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "intent"]))

    def test_draft_leaves_spec_approved(self):
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "draft"],
                                       labels=("sdd:stage:spec-approved",)))

    def test_tdd_leaves_implementing(self):
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "tdd"],
                                       labels=("sdd:stage:implementing",)))

    def test_reconcile_allowed_labels(self):
        for label in ("implementing", "complete"):
            self.assert_ok(*self.run_check(["--issue", "7", "--stage", "reconcile"],
                                           labels=("sdd:stage:" + label,)))

    def test_pr_validate_allowed_labels(self):
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "pr-validate"],
                                       labels=("sdd:stage:verified",)))
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "pr-validate", "--stopped"],
                                       labels=("sdd:stage:complete",)))

    def test_wrong_label_fails(self):
        self.assert_fail(*self.run_check(["--issue", "7", "--stage", "tdd"],
                                         labels=("sdd:stage:complete",)))
        argv = ["--issue", "7", "--stage", "intent"]
        self.assert_fail(*self.run_check(argv, body=BODY.replace("x", "implementing")))
        self.assert_fail(*self.run_check(argv, body="**Branch:** sdd/7-demo\n"))
        self.assert_fail(*self.run_check(argv, issue_state="CLOSED"))
        self.assert_fail(*self.run_check(argv + ["--worktree", "/w"], issue_state="CLOSED",
                                         body="**Stage:** drafting-spec\n"))
        twice = BODY.replace("x", "drafting-spec") + "**Stage:** drafting-spec\n"
        self.assert_fail(*self.run_check(argv, body=twice))

    def test_draft_with_needs_spec_fails(self):
        self.assert_fail(*self.run_check(["--issue", "7", "--stage", "draft"],
                                         labels=("sdd:stage:spec-approved",), needs_spec=["12"]))

    def test_reconcile_drafting_without_needs_spec_fails(self):
        self.assert_fail(*self.run_check(["--issue", "7", "--stage", "reconcile"]))
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "reconcile"], needs_spec=["12"]))

    def test_complete_without_stopped_fails(self):
        self.assert_fail(*self.run_check(["--issue", "7", "--stage", "pr-validate"],
                                         labels=("sdd:stage:complete",)))

    def test_wrong_branch_fails(self):
        self.assert_fail(*self.run_check(["--issue", "7", "--stage", "intent", "--worktree", "/w"],
                                         branch="other"))
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "intent", "--worktree", "/w"]))

    def test_main_status_changed_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rec = pathlib.Path(tmp) / "status.txt"
            rec.write_text("?? a\n")
            argv = ["--issue", "7", "--stage", "intent", "--main-checkout", "/m",
                    "--status-file", str(rec), "--main-sha", "abc"]
            self.assert_ok(*self.run_check(argv, status="?? a"))
            self.assert_fail(*self.run_check(argv, status="?? a\n?? b"))

    def test_main_moved_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rec = pathlib.Path(tmp) / "status.txt"
            rec.write_text("")
            argv = ["--issue", "7", "--stage", "intent", "--main-checkout", "/m",
                    "--status-file", str(rec), "--main-sha", "abc"]
            self.assert_fail(*self.run_check(argv, main_sha="def"))

    def test_open_child_fails(self):
        argv = ["--issue", "7", "--stage", "intent", "--child", "9"]
        self.assert_fail(*self.run_check(argv, child_state="OPEN"))

    def test_all_checks_pass(self):
        self.assert_ok(*self.run_check(["--issue", "7", "--stage", "intent", "--worktree", "/w",
                                        "--child", "9"]))

    def test_usage_and_tool_errors_exit_2(self):
        base = ["--issue", "7"]
        self.assertEqual(self.run_check(base + ["--stage", "bogus"])[0], 2)
        self.assertEqual(self.run_check(base + ["--stage", "intent", "--main-checkout", "/m"])[0], 2)
        self.assertEqual(self.run_check(base + ["--stage", "intent", "--main-sha", "abc"])[0], 2)
        self.assertEqual(self.run_check(base + ["--stage", "intent", "--stopped"])[0], 2)
        for body in ("no branch line", "**Branch:** weird"):
            self.assertEqual(self.run_check(base + ["--stage", "intent", "--worktree", "/w"],
                                            body=body)[0], 2)
        self.assertEqual(self.run_check(base + ["--stage", "intent"], gh_fail=True)[0], 2)
        self.assertEqual(self.run_check(base + ["--stage", "intent"], gh_raw="not json")[0], 2)
        # argparse's help exits 0, which the orchestrator would read as a pass.
        self.assertEqual(self.run_check(base + ["--stage", "intent", "--help"])[0], 2)
        # A missing gh or git binary is a tool error, not a traceback.
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("gh")):
            for call in (lambda: sdd_check_state.run_gh(["issue", "view", "7"]),
                         lambda: sdd_check_state.run_git("/w", "status")):
                with self.assertRaises(sdd_check_state.ToolError):
                    call()

    def test_stage_line_pattern_matches_set_stage(self):
        path = pathlib.Path(__file__).resolve().parent / "set-stage.py"
        spec = importlib.util.spec_from_file_location("set_stage", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual((sdd_check_state.STAGE_LINE_RE.pattern, sdd_check_state.STAGE_LINE_RE.flags),
                         (module.STAGE_LINE_RE.pattern, module.STAGE_LINE_RE.flags))


if __name__ == "__main__":
    unittest.main()
