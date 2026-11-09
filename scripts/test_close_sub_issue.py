"""Stdlib tests for close-sub-issue.py; `gh` is faked, git runs on a throwaway repo.

Run: python3 -m unittest discover -s .claude/skills/sdd-tdd/scripts -v
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "close_sub_issue", pathlib.Path(__file__).with_name("close-sub-issue.py")
)
close_sub_issue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(close_sub_issue)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class FakeGh:
    """Serves one sub-issue's state and labels, and records the close."""

    def __init__(self, state="OPEN", labels=("sdd:task",), closes=True):
        self.state = state
        self.labels = list(labels)
        self.closes = closes
        self.calls = []

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        if args[:2] == ["issue", "view"]:
            return json.dumps(
                {"state": self.state, "labels": [{"name": n} for n in self.labels]}
            )
        if args[:2] == ["issue", "close"]:
            if self.closes:
                self.state = "CLOSED"
            return ""
        raise AssertionError(f"unexpected gh call: {args}")

    def closed(self):
        return any(c[:2] == ["issue", "close"] for c in self.calls)


class Repo(unittest.TestCase):
    """A repo on `feature` with a red-green pair for #7 and a gate marker on its tree."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        git(self.repo, "config", "commit.gpgsign", "false")
        self.n = 0
        self.commit("chore: base")
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("test: red scenario (#7)")
        self.commit("feat: make it pass (#7)")
        self.mark()
        self.gh = FakeGh()
        close_sub_issue.run_gh = self.gh
        close_sub_issue.sub_issues = lambda parent: (
            [{"number": 7, "state": self.gh.state, "title": "T"}] if parent == 5 else []
        )

    def commit(self, subject):
        self.n += 1
        (self.repo / f"f{self.n}.txt").write_text(f"{self.n}\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", subject)

    def mark(self):
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        rel = git(self.repo, "rev-parse", "--git-path", f"sdd-gate/{tree}")
        path = pathlib.Path(rel)
        path = path if path.is_absolute() else self.repo / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n")

    def close(self, main=5, child=7):
        return close_sub_issue.close(main, child, repo=self.repo, base="main")


class Close(Repo):
    def test_given_marker_and_pair_then_the_sub_issue_is_closed(self):
        # Given a clean tree with a gate marker and a test: → feat: pair
        # When the sub-issue is closed
        ok, message = self.close()
        # Then it is closed as completed and the re-read shows CLOSED
        self.assertTrue(ok, message)
        self.assertIn(["issue", "close", "7", "--reason", "completed"], self.gh.calls)
        self.assertEqual(self.gh.state, "CLOSED")

    def test_given_not_a_sub_issue_of_main_then_it_refuses(self):
        # Given #7 is not a sub-issue of #6
        ok, message = self.close(main=6)
        # Then nothing is closed
        self.assertFalse(ok)
        self.assertIn("not a sub-issue", message)
        self.assertFalse(self.gh.closed())

    def test_given_an_already_closed_sub_issue_then_it_refuses(self):
        self.gh.state = "CLOSED"
        ok, message = self.close()
        self.assertFalse(ok)
        self.assertIn("not open", message)
        self.assertFalse(self.gh.closed())

    def test_given_no_sdd_task_label_then_it_refuses(self):
        self.gh.labels = ["bug"]
        ok, message = self.close()
        self.assertFalse(ok)
        self.assertIn("sdd:task", message)
        self.assertFalse(self.gh.closed())

    def test_given_a_dirty_tree_then_it_refuses(self):
        # Given an untracked file next to the marked tree
        (self.repo / "stray.txt").write_text("x\n")
        ok, message = self.close()
        self.assertFalse(ok)
        self.assertIn("not clean", message)
        self.assertFalse(self.gh.closed())

    def test_given_no_marker_on_head_tree_then_it_refuses(self):
        # Given a new commit after the gate ran, so the marker is on an old tree
        self.commit("chore: later change (#7)")
        ok, message = self.close()
        self.assertFalse(ok)
        self.assertIn("gate marker", message)
        self.assertFalse(self.gh.closed())

    def test_given_no_red_green_pair_then_it_refuses(self):
        # Given a sub-issue whose only commit is feat:
        self.commit("feat: no red first (#8)")
        self.mark()
        close_sub_issue.sub_issues = lambda parent: [{"number": 8, "state": "OPEN", "title": "T"}]
        ok, message = self.close(child=8)
        self.assertFalse(ok)
        self.assertIn("#8", message)
        self.assertFalse(self.gh.closed())

    def test_given_no_red_green_label_then_the_pair_check_is_skipped(self):
        # Given an exempt sub-issue with only a docs: commit
        self.commit("docs: declare the hook (#8)")
        self.mark()
        self.gh.labels = ["sdd:task", "sdd:no-red-green"]
        close_sub_issue.sub_issues = lambda parent: [{"number": 8, "state": "OPEN", "title": "T"}]
        ok, message = self.close(child=8)
        self.assertTrue(ok, message)
        self.assertTrue(self.gh.closed())

    def test_given_the_close_does_not_land_then_it_fails(self):
        # Given gh accepts the close but the re-read still shows OPEN
        self.gh.closes = False
        ok, message = self.close()
        self.assertFalse(ok)
        self.assertIn("OPEN", message)


class SecurityMarkerGate(Repo):
    """close() additionally requires the security marker when `security_commands` is
    configured, via the same narrow `sdd_flow_config.load_security_commands()` read
    `sdd_gate_guard.py` uses for `set-stage.py <n> complete|verified`."""

    def configure(self, frontmatter_body):
        path = self.repo / ".claude"
        path.mkdir(parents=True, exist_ok=True)
        (path / "sdd-flow.local.md").write_text(f"---\n{frontmatter_body}\n---\n", encoding="utf-8")
        self.commit("chore: configure (#7)")
        self.mark()

    def write_security_marker(self):
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        rel = git(self.repo, "rev-parse", "--git-path", f"sdd-security/{tree}")
        path = pathlib.Path(rel)
        path = path if path.is_absolute() else self.repo / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n")

    def test_given_security_commands_configured_without_marker_then_it_refuses(self):
        # Given security_commands configured but the security scan never ran
        self.configure('security_commands: [{name: "ok", run: "true"}]')
        # When the sub-issue is closed
        ok, message = self.close()
        # Then it refuses: the gate marker alone is not enough
        self.assertFalse(ok)
        self.assertIn("security marker", message)
        self.assertFalse(self.gh.closed())

    def test_given_security_commands_configured_with_marker_then_it_closes(self):
        # Given security_commands configured and the security scan already ran on this tree
        self.configure('security_commands: [{name: "ok", run: "true"}]')
        self.write_security_marker()
        # When the sub-issue is closed
        ok, message = self.close()
        # Then it closes: both markers match the clean tree
        self.assertTrue(ok, message)
        self.assertTrue(self.gh.closed())

    def test_given_unreadable_security_commands_then_it_refuses(self):
        # Given a config file whose frontmatter is never closed with a second `---` line
        path = self.repo / ".claude"
        path.mkdir(parents=True, exist_ok=True)
        (path / "sdd-flow.local.md").write_text("---\nsecurity_commands: []\n", encoding="utf-8")
        self.commit("chore: configure (#7)")
        self.mark()
        # When the sub-issue is closed
        ok, message = self.close()
        # Then it refuses: fail-closed, the same as an unreadable build-gate marker
        self.assertFalse(ok)
        self.assertIn("security_commands", message)
        self.assertFalse(self.gh.closed())


class Main(Repo):
    def test_main_exits_zero_on_a_close(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = close_sub_issue.main(["5", "7", "--repo", str(self.repo)])
        self.assertEqual(code, 0)
        self.assertIn("#7", out.getvalue())

    def test_main_exits_non_zero_and_names_the_reason_on_a_refusal(self):
        (self.repo / "stray.txt").write_text("x\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = close_sub_issue.main(["5", "7", "--repo", str(self.repo)])
        self.assertNotEqual(code, 0)
        self.assertIn("not clean", err.getvalue())


if __name__ == "__main__":
    unittest.main()
