"""Stdlib unit tests for verify_red_green. Run: python3 -m unittest discover -s <this folder>"""
import contextlib
import importlib.util
import io
import pathlib
import subprocess
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "verify_red_green", pathlib.Path(__file__).with_name("verify_red_green.py")
)
verify_red_green = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_red_green)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Repo(unittest.TestCase):
    """A throwaway repo with one commit on `main` and a feature branch checked out."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / "base.txt").write_text("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "chore: base")
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.n = 0

    def commit(self, subject, change=True):
        if change:
            self.n += 1
            (self.repo / f"f{self.n}.txt").write_text(f"{self.n}\n")
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-q", "-m", subject)
        else:
            git(self.repo, "commit", "-q", "--allow-empty", "-m", subject)

    def verify(self, child=7):
        return verify_red_green.verify(child, repo=self.repo, base="main")


class Verify(Repo):
    def test_test_then_feat_passes(self):
        # Given a test: commit then a feat: commit for #7
        self.commit("test: red scenario (#7)")
        self.commit("feat: make it pass (#7)")
        # When the pair is verified
        ok, _ = self.verify()
        # Then it passes
        self.assertTrue(ok)

    def test_test_then_fix_passes(self):
        # Given a test: commit then a fix: commit for #7
        self.commit("test: red scenario (#7)")
        self.commit("fix: make it pass (#7)")
        # Then it passes
        self.assertTrue(self.verify()[0])

    def test_feat_before_test_fails(self):
        # Given the feat: commit comes before the test: commit
        self.commit("feat: code first (#7)")
        self.commit("test: test after (#7)")
        # Then it fails
        ok, message = self.verify()
        self.assertFalse(ok)
        self.assertIn("#7", message)

    def test_feat_without_test_fails(self):
        # Given only a feat: commit
        self.commit("feat: code only (#7)")
        # Then it fails
        self.assertFalse(self.verify()[0])

    def test_test_without_feat_fails(self):
        # Given only a test: commit
        self.commit("test: red only (#7)")
        # Then it fails
        self.assertFalse(self.verify()[0])

    def test_no_commits_fails(self):
        # Given no commit for #7 at all
        self.commit("feat: other work (#8)")
        # Then it fails
        self.assertFalse(self.verify()[0])

    def test_empty_test_commit_fails(self):
        # Given an empty test: commit before the feat: commit
        self.commit("test: nothing (#7)", change=False)
        self.commit("feat: make it pass (#7)")
        # Then it fails, because the red commit is empty
        ok, message = self.verify()
        self.assertFalse(ok)
        self.assertIn("empty", message)

    def test_other_sub_issue_commits_are_ignored(self):
        # Given the test: commit belongs to #8, not #7
        self.commit("test: red for eight (#8)")
        self.commit("feat: make it pass (#7)")
        # Then #7 fails
        self.assertFalse(self.verify()[0])

    def test_number_prefix_does_not_match(self):
        # Given commits for #70, whose number starts with 7
        self.commit("test: red (#70)")
        self.commit("feat: green (#70)")
        # Then #7 fails, and #70 passes
        self.assertFalse(self.verify(7)[0])
        self.assertTrue(self.verify(70)[0])

    def test_other_commit_types_between_are_allowed(self):
        # Given a docs: commit between the red and green commits
        self.commit("test: red (#7)")
        self.commit("docs: note (#7)")
        self.commit("feat: green (#7)")
        # Then it passes
        self.assertTrue(self.verify()[0])

    def test_commits_already_on_main_are_ignored(self):
        # Given a test: commit for #7 that is on main, not on the branch
        git(self.repo, "checkout", "-q", "main")
        self.commit("test: red on main (#7)")
        git(self.repo, "checkout", "-q", "feature")
        self.commit("feat: green (#7)")
        # Then it fails
        self.assertFalse(self.verify()[0])

    def test_scoped_type_is_accepted(self):
        # Given conventional-commit scopes on both commits
        self.commit("test(skills): red (#7)")
        self.commit("feat(skills): green (#7)")
        # Then it passes
        self.assertTrue(self.verify()[0])


class Cli(Repo):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verify_red_green.main([*args, "--repo", str(self.repo), "--base", "main"])
        return code, out.getvalue(), err.getvalue()

    def test_cli_exits_zero_on_a_pair(self):
        # Given a red-green pair for #7
        self.commit("test: red (#7)")
        self.commit("feat: green (#7)")
        # When the CLI runs for #7
        code, out, _ = self.run_cli("7")
        # Then it exits 0
        self.assertEqual(code, 0)
        self.assertIn("#7", out)

    def test_cli_exits_non_zero_without_a_pair(self):
        # Given only a feat: commit for #7
        self.commit("feat: green (#7)")
        # When the CLI runs for #7
        code, _, err = self.run_cli("7")
        # Then it exits non-zero with the reason on stderr
        self.assertNotEqual(code, 0)
        self.assertIn("#7", err)


if __name__ == "__main__":
    unittest.main()
