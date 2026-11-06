"""Stdlib unit tests for run_security_commands. Run: python3 -m unittest scripts.test_run_security_commands -v"""
import contextlib
import importlib.util
import io
import pathlib
import subprocess
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "run_security_commands", pathlib.Path(__file__).with_name("run_security_commands.py")
)
run_security_commands = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_security_commands)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Repo(unittest.TestCase):
    """A throwaway git repository with one commit, matching test_gate_marker.py's fixture."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / "a.txt").write_text("a\n")
        self.commit("first")

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def tree(self):
        return git(self.repo, "rev-parse", "HEAD^{tree}")

    def configure(self, security_commands_line):
        """Write `.claude/sdd-flow.local.md` with one `security_commands: ...` line, and
        commit it, so the fixture's own configuring step never leaves the tree dirty."""
        path = self.repo / ".claude"
        path.mkdir(parents=True, exist_ok=True)
        (path / "sdd-flow.local.md").write_text(
            f"---\n{security_commands_line}\n---\n", encoding="utf-8"
        )
        self.commit("configure")


class RunsNoCommandsWhenUnset(Repo):
    def test_runs_no_commands_when_unset(self):
        # Given no security_commands configured (the default, no config file at all)
        # When the security gate runs
        ok, message = run_security_commands.run(self.repo)
        # Then it passes and writes no marker
        self.assertTrue(ok)
        self.assertFalse(run_security_commands.marker_path(self.repo, self.tree()).exists())


class FailsWhenAnyCommandExitsNonzero(Repo):
    def test_fails_when_any_command_exits_nonzero(self):
        # Given a configured command that fails
        self.configure('security_commands: [{name: "bad", run: "exit 1"}, {name: "good", run: "true"}]')
        tree = self.tree()
        # When the security gate runs
        ok, message = run_security_commands.run(self.repo)
        # Then it fails, naming the command, and writes no marker
        self.assertFalse(ok)
        self.assertIn("bad", message)
        self.assertFalse(run_security_commands.marker_path(self.repo, tree).exists())


class FailsWhenAnEntryHasNoRunCommand(Repo):
    def test_fails_when_an_entry_has_no_run_command(self):
        # Given a configured entry missing its `run` field (a plausible typo) — not a
        # real scan, so it must never be treated as a silent pass
        self.configure('security_commands: [{name: "eslint-security"}]')
        tree = self.tree()
        # When the security gate runs
        ok, message = run_security_commands.run(self.repo)
        # Then it fails, naming the entry, and writes no marker
        self.assertFalse(ok)
        self.assertIn("eslint-security", message)
        self.assertFalse(run_security_commands.marker_path(self.repo, tree).exists())


class WritesMarkerWhenAllCommandsPassAndTreeStillClean(Repo):
    def test_writes_marker_when_all_commands_pass_and_tree_still_clean(self):
        # Given every configured command exits zero and touches nothing
        self.configure('security_commands: [{name: "ok", run: "true"}]')
        tree = self.tree()
        # When the security gate runs
        ok, message = run_security_commands.run(self.repo)
        # Then it passes and writes the marker at sdd-security/<tree>
        self.assertTrue(ok)
        path = run_security_commands.marker_path(self.repo, tree)
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, tree)
        self.assertEqual(path.parent.name, "sdd-security")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")


class WriteWhenTreeDirtyAtTheEndWritesNoMarker(Repo):
    def test_write_when_tree_dirty_at_the_end_writes_no_marker(self):
        # Given a command that exits zero but leaves an untracked file behind
        self.configure('security_commands: [{name: "dirty", run: "echo x > new.txt"}]')
        tree = self.tree()
        # When the security gate runs
        ok, message = run_security_commands.run(self.repo)
        # Then the step itself still passed, but no marker was written
        self.assertTrue(ok)
        self.assertFalse(run_security_commands.marker_path(self.repo, tree).exists())


class WriteWhenTreeChangedDuringTheGateWritesNoMarker(Repo):
    def test_write_when_tree_changed_during_the_gate_writes_no_marker(self):
        # Given a command that exits zero but commits new content mid-run (an empty
        # commit leaves HEAD^{tree} unchanged, so the content must actually change)
        self.configure(
            'security_commands: [{name: "commits", run: '
            '"echo changed > a.txt && git add -A && git commit -q -m second"}]'
        )
        tree_before = self.tree()
        # When the security gate runs
        ok, message = run_security_commands.run(self.repo)
        # Then it passed, but no marker was written for either tree
        self.assertTrue(ok)
        self.assertFalse(run_security_commands.marker_path(self.repo, tree_before).exists())
        self.assertFalse(run_security_commands.marker_path(self.repo, self.tree()).exists())


class Cli(Repo):
    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return run_security_commands.main(["--repo", str(self.repo), *args])

    def test_main_exits_zero_when_no_commands_are_configured(self):
        self.assertEqual(self.run_cli(), 0)

    def test_main_exits_non_zero_when_a_command_fails(self):
        self.configure('security_commands: [{name: "bad", run: "exit 1"}]')
        self.assertEqual(self.run_cli(), 1)


if __name__ == "__main__":
    unittest.main()
