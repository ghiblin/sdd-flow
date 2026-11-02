"""Stdlib tests for resolve-issue.py; `git` is faked.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import contextlib
import importlib.util
import io
import pathlib
import unittest

_spec = importlib.util.spec_from_file_location(
    "resolve_issue", pathlib.Path(__file__).with_name("resolve-issue.py")
)
resolve_issue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve_issue)


def fake_git(branch):
    calls = []

    def run_git(args):
        calls.append(list(args))
        assert args == ["rev-parse", "--abbrev-ref", "HEAD"], args
        return branch

    run_git.calls = calls
    return run_git


class ResolveIssue(unittest.TestCase):
    def test_given_an_sdd_branch_when_resolved_then_returns_its_number(self):
        resolve_issue.run_git = fake_git("sdd/307-sdd-skill-scripts")
        self.assertEqual(resolve_issue.resolve_issue(), 307)

    def test_given_an_explicit_branch_then_git_is_not_called(self):
        git = fake_git("main")
        resolve_issue.run_git = git
        self.assertEqual(resolve_issue.resolve_issue("sdd/12-x"), 12)
        self.assertEqual(git.calls, [])

    def test_given_a_non_sdd_branch_then_it_exits_non_zero(self):
        for branch in ("main", "sdd/abc-x", "feature/12-x", "sdd/12", "xsdd/12-x"):
            resolve_issue.run_git = fake_git(branch)
            with self.subTest(branch=branch), self.assertRaises(SystemExit) as ctx:
                resolve_issue.resolve_issue()
            self.assertNotEqual(ctx.exception.code, 0)
            self.assertIn("sdd-intent", str(ctx.exception.code))

    def test_main_prints_the_number(self):
        resolve_issue.run_git = fake_git("sdd/9-a-b")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            resolve_issue.main([])
        self.assertEqual(out.getvalue(), "9\n")

    def test_main_accepts_a_branch_argument(self):
        resolve_issue.run_git = fake_git("main")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            resolve_issue.main(["--branch", "sdd/41-y"])
        self.assertEqual(out.getvalue(), "41\n")


if __name__ == "__main__":
    unittest.main()
