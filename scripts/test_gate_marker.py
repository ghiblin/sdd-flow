"""Stdlib unit tests for gate_marker. Run: python3 -m unittest scripts.test_gate_marker -v"""
import contextlib
import importlib.util
import io
import pathlib
import subprocess
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "gate_marker", pathlib.Path(__file__).with_name("gate_marker.py")
)
gate_marker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_marker)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class Repo(unittest.TestCase):
    """A throwaway git repository with one commit and a .gitignore."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / ".gitignore").write_text("ignored/\n")
        (self.repo / "a.txt").write_text("a\n")
        self.commit("first")

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def tree(self, repo=None):
        return git(repo or self.repo, "rev-parse", "HEAD^{tree}")


def load_close_helper():
    path = pathlib.Path(__file__).with_name("close-sub-issue.py")
    spec = importlib.util.spec_from_file_location("close_sub_issue", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MarkerLayoutAgrees(Repo):
    """close-sub-issue.py finds the marker exactly where gate_marker.py writes it.

    sdd-flow ships one shared close-sub-issue.py (unlike diet-pal's per-skill copies),
    so there is one layout to check, not one per skill.
    """

    def assert_layout_agrees(self, repo):
        tree = self.tree(repo)
        self.assertTrue(gate_marker.write(repo, tree))
        helper = load_close_helper()
        self.assertEqual(helper.marker_file(repo, tree), gate_marker.marker_path(repo, tree))
        self.assertTrue(helper.marker_file(repo, tree).is_file())

    def test_given_the_main_checkout_then_both_paths_agree(self):
        self.assert_layout_agrees(self.repo)

    def test_given_a_linked_worktree_then_both_paths_agree(self):
        linked = pathlib.Path(self._tmp.name) / "linked"
        git(self.repo, "worktree", "add", "-q", "-b", "side", str(linked))
        self.assert_layout_agrees(linked)


class CleanTree(Repo):
    def test_clean_repo_gives_head_tree(self):
        # Given a repo with no change
        # When the clean tree is read
        # Then it is HEAD^{tree}
        self.assertEqual(gate_marker.tree_if_clean(self.repo), self.tree())

    def test_modified_tracked_file_gives_none(self):
        # Given a modified tracked file
        (self.repo / "a.txt").write_text("changed\n")
        # Then the tree is not clean
        self.assertIsNone(gate_marker.tree_if_clean(self.repo))

    def test_staged_change_gives_none(self):
        # Given a staged change
        (self.repo / "a.txt").write_text("changed\n")
        git(self.repo, "add", "a.txt")
        # Then the tree is not clean
        self.assertIsNone(gate_marker.tree_if_clean(self.repo))

    def test_untracked_unignored_file_gives_none(self):
        # Given a new file git does not ignore
        (self.repo / "new.txt").write_text("x\n")
        # Then the tree is not clean
        self.assertIsNone(gate_marker.tree_if_clean(self.repo))

    def test_ignored_file_keeps_tree_clean(self):
        # Given a new file git ignores
        (self.repo / "ignored").mkdir()
        (self.repo / "ignored" / "out.bin").write_text("x\n")
        # Then the tree is still clean
        self.assertEqual(gate_marker.tree_if_clean(self.repo), self.tree())


class WriteAndCheck(Repo):
    def test_write_on_clean_matching_tree_creates_marker_outside_work_tree(self):
        # Given a clean tree read before the gate ran
        tree = gate_marker.tree_if_clean(self.repo)
        # When the marker is written after the gate passed
        self.assertTrue(gate_marker.write(self.repo, tree))
        # Then the marker sits in the git dir, named after the tree
        path = gate_marker.marker_path(self.repo, tree)
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, tree)
        self.assertEqual(path.parent.name, "sdd-gate")
        self.assertIn(".git", path.parts)
        # And the work tree stays clean, and the check passes
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertTrue(gate_marker.check(self.repo))

    def test_write_without_a_start_tree_writes_nothing(self):
        # Given the tree was dirty when the gate started (no start tree)
        # When the marker is written
        # Then nothing is written and the check fails
        self.assertFalse(gate_marker.write(self.repo, None))
        self.assertFalse(gate_marker.write(self.repo, ""))
        self.assertFalse(gate_marker.check(self.repo))

    def test_write_when_tree_changed_during_the_gate_writes_nothing(self):
        # Given a clean tree read before the gate ran
        tree = gate_marker.tree_if_clean(self.repo)
        # When a content commit lands before the marker is written
        (self.repo / "a.txt").write_text("changed\n")
        self.commit("second")
        # Then no marker is written for either tree
        self.assertFalse(gate_marker.write(self.repo, tree))
        self.assertFalse(gate_marker.marker_path(self.repo, tree).exists())
        self.assertFalse(gate_marker.check(self.repo))

    def test_write_when_tree_dirty_at_the_end_writes_nothing(self):
        # Given a clean tree read before the gate ran
        tree = gate_marker.tree_if_clean(self.repo)
        # When the tree is dirty when the marker is written
        (self.repo / "new.txt").write_text("x\n")
        # Then nothing is written
        self.assertFalse(gate_marker.write(self.repo, tree))
        self.assertFalse(gate_marker.marker_path(self.repo, tree).exists())

    def test_check_fails_on_dirty_tree_even_with_a_marker(self):
        # Given a marker for the current tree
        gate_marker.write(self.repo, gate_marker.tree_if_clean(self.repo))
        # When the tree becomes dirty
        (self.repo / "a.txt").write_text("changed\n")
        # Then the check fails
        self.assertFalse(gate_marker.check(self.repo))

    def test_content_commit_needs_a_new_gate_run(self):
        # Given a marker for the current tree
        gate_marker.write(self.repo, gate_marker.tree_if_clean(self.repo))
        # When a commit changes content
        (self.repo / "a.txt").write_text("changed\n")
        self.commit("second")
        # Then the check fails
        self.assertFalse(gate_marker.check(self.repo))

    def test_message_amend_keeps_the_marker(self):
        # Given a marker for the current tree
        gate_marker.write(self.repo, gate_marker.tree_if_clean(self.repo))
        # When only the commit message is amended
        git(self.repo, "commit", "-q", "--amend", "-m", "reworded")
        # Then the check still passes
        self.assertTrue(gate_marker.check(self.repo))

    def test_each_worktree_keeps_its_own_markers(self):
        # Given a linked worktree on a branch with different content
        wt = pathlib.Path(self._tmp.name) / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "feature", str(wt))
        (wt / "b.txt").write_text("b\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "feature")
        # When the gate marker is written in the linked worktree
        self.assertTrue(gate_marker.write(wt, gate_marker.tree_if_clean(wt)))
        # Then it lives in that worktree's own git dir
        path = gate_marker.marker_path(wt, self.tree(wt))
        self.assertIn("worktrees", path.parts)
        self.assertTrue(gate_marker.check(wt))
        # And the main checkout has no marker
        self.assertFalse(gate_marker.check(self.repo))


class Cli(Repo):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = gate_marker.main(["--repo", str(self.repo), *args])
        return code, out.getvalue().strip()

    def test_clean_tree_prints_the_tree(self):
        self.assertEqual(self.run_cli("clean-tree"), (0, self.tree()))

    def test_clean_tree_prints_nothing_when_dirty(self):
        (self.repo / "new.txt").write_text("x\n")
        self.assertEqual(self.run_cli("clean-tree"), (0, ""))

    def test_write_then_check(self):
        # Given no marker, the check exits non-zero
        self.assertEqual(self.run_cli("check")[0], 1)
        # When the marker is written for the clean start tree
        self.assertEqual(self.run_cli("write", self.tree())[0], 0)
        # Then the check exits zero
        self.assertEqual(self.run_cli("check")[0], 0)

    def test_write_without_tree_exits_zero_and_writes_nothing(self):
        # A gate that passed on a dirty tree still passes; it only gets no marker
        self.assertEqual(self.run_cli("write", "")[0], 0)
        self.assertEqual(self.run_cli("check")[0], 1)


# A `CheckSh` class testing a concrete project's own `scripts/check.sh` lived here in
# diet-pal — that file is product-specific (its own cargo/clippy/test commands) and is
# never shipped by sdd-flow. docs/config-reference.md documents the wiring contract
# (read the clean tree before the gate, write the marker only after it passes) for a
# consuming project's own gate script to follow; there is nothing generic left to test here.


if __name__ == "__main__":
    unittest.main()
