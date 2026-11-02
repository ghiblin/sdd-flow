"""Stdlib unit tests for the sdd_gate_guard PreToolUse hook.

Run: python3 -m unittest scripts.test_sdd_gate_guard -v
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "sdd_gate_guard.py"
GATE_MARKER = pathlib.Path(__file__).with_name("gate_marker.py")

_spec = importlib.util.spec_from_file_location("sdd_gate_guard", HOOK)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def bash(command, cwd="/nowhere"):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


def run_hook(data):
    """Run the hook as Claude Code does: JSON on stdin, decision on stdout."""
    result = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(data), capture_output=True, text=True
    )
    return result.returncode, result.stdout


class RawCloseAndLabels(unittest.TestCase):
    def test_given_raw_gh_issue_close_when_checked_then_denied(self):
        self.assertIsNotNone(guard.decide(bash("gh issue close 379 --reason completed")))

    def test_given_gh_issue_close_after_cd_when_checked_then_denied(self):
        self.assertIsNotNone(guard.decide(bash("cd /tmp/wt && gh issue close 379")))

    def test_given_close_sub_issue_helper_when_checked_then_allowed(self):
        cmd = "python3 .claude/skills/sdd-tdd/scripts/close-sub-issue.py 352 379"
        self.assertIsNone(guard.decide(bash(cmd)))

    def test_given_gh_issue_view_when_checked_then_allowed(self):
        self.assertIsNone(guard.decide(bash("gh issue view 379 --json state")))

    def test_given_edit_adding_stage_complete_when_checked_then_denied(self):
        cmd = "gh issue edit 352 --add-label sdd:stage:complete --remove-label sdd:stage:implementing"
        self.assertIsNotNone(guard.decide(bash(cmd)))

    def test_given_edit_adding_stage_verified_with_equals_when_checked_then_denied(self):
        self.assertIsNotNone(guard.decide(bash("gh issue edit 352 --add-label=sdd:stage:verified")))

    def test_given_edit_adding_no_red_green_in_label_list_when_checked_then_denied(self):
        cmd = 'gh issue edit 379 --add-label "sdd:task,sdd:no-red-green"'
        self.assertIsNotNone(guard.decide(bash(cmd)))

    def test_given_edit_removing_no_red_green_when_checked_then_allowed(self):
        self.assertIsNone(guard.decide(bash("gh issue edit 379 --remove-label sdd:no-red-green")))

    def test_given_edit_adding_stage_implementing_when_checked_then_allowed(self):
        cmd = "gh issue edit 352 --add-label sdd:stage:implementing"
        self.assertIsNone(guard.decide(bash(cmd)))

    def test_raw_spec_approved_label_is_denied(self):
        cmd = "gh issue edit 363 --add-label sdd:stage:spec-approved"
        self.assertIsNotNone(guard.decide(bash(cmd)))
        self.assertIsNotNone(guard.decide(bash("gh issue edit 363 --add-label SDD:Stage:Spec-Approved")))

    def test_set_stage_spec_approved_is_allowed(self):
        cmd = "python3 .claude/skills/sdd-draft/scripts/set-stage.py 363 spec-approved"
        self.assertIsNone(guard.decide(bash(cmd)))

    def test_given_non_bash_tool_when_checked_then_allowed(self):
        data = {"tool_name": "Read", "tool_input": {"file_path": "gh issue close"}}
        self.assertIsNone(guard.decide(data))


class Bypasses(unittest.TestCase):
    """Global flags, nested shells, other gh verbs and letter case do not get past the hook."""

    def denied(self, cmd):
        self.assertIsNotNone(guard.decide(bash(cmd)), cmd)

    def allowed(self, cmd):
        self.assertIsNone(guard.decide(bash(cmd)), cmd)

    def test_given_gh_global_repo_flag_before_issue_when_closing_then_denied(self):
        self.denied("gh -R owner/repo issue close 5")
        self.denied("gh --repo o/r issue edit 5 --add-label sdd:stage:complete")

    def test_given_close_in_a_nested_shell_or_eval_when_checked_then_denied(self):
        self.denied('bash -c "gh issue close 5"')
        self.denied("sh -ec 'gh issue close 5'")
        self.denied('eval "gh issue close $c"')

    def test_given_close_in_a_command_substitution_when_checked_then_denied(self):
        self.denied("x=$(gh issue close 5)")
        self.denied("echo `gh issue close 5`")

    def test_given_label_in_any_letter_case_when_added_then_denied(self):
        self.denied("gh issue edit 352 --add-label SDD:Stage:Complete")
        self.denied("gh issue edit 352 --add-label SDD:NO-RED-GREEN")

    def test_given_label_in_a_variable_when_added_then_denied(self):
        self.denied('gh issue edit 352 --add-label "$label"')

    def test_given_issue_create_with_a_guarded_label_when_checked_then_denied(self):
        self.denied("gh issue create --title X --label sdd:task --label sdd:no-red-green")
        self.denied("gh issue create -t X -l sdd:no-red-green")
        self.allowed("gh issue create --title X --label sdd:task")

    def test_given_gh_api_close_or_label_write_when_checked_then_denied(self):
        self.denied("gh api -X PATCH repos/o/r/issues/5 -f state=closed")
        self.denied("gh api repos/o/r/issues/5/labels -f 'labels[]=sdd:no-red-green'")
        self.denied("gh api graphql -f query='mutation { closeIssue(input: {issueId: \"x\"}) { clientMutationId } }'")
        self.allowed("gh api repos/o/r/issues/5 --jq .state")

    def test_given_heredoc_body_naming_a_close_when_committing_then_allowed(self):
        self.allowed("git commit -F - <<'EOF'\nfix: replace gh issue close with close-sub-issue.py\nEOF")
        self.allowed("cat > notes.md <<EOF\ngh issue close 5\nEOF\ngit status")

    def test_given_command_after_a_heredoc_when_it_closes_then_denied(self):
        self.denied("cat > notes.md <<EOF\ntext\nEOF\ngh issue close 5")

    def test_given_quoted_heredoc_operator_when_checked_then_the_next_line_still_counts(self):
        self.denied('echo "<<EOF"\ngh issue close 5')

    def test_given_a_quoted_substitution_when_it_closes_then_denied(self):
        self.denied('echo "$(gh issue close 5)"')
        self.denied('x="$(gh issue close 5)"')
        self.denied('echo "`gh issue close 5`"')

    def test_given_a_heredoc_fed_to_a_shell_when_it_closes_then_denied(self):
        self.denied("bash <<EOF\ngh issue close 5\nEOF")
        self.denied("cat <<'EOF' | sh\ngh issue close 5\nEOF")

    def test_given_an_unquoted_heredoc_with_a_substitution_when_it_closes_then_denied(self):
        self.denied("cat <<EOF\n$(gh issue close 5)\nEOF")
        # A quoted delimiter expands nothing, so the body stays data.
        self.allowed("cat <<'EOF'\n$(gh issue close 5)\nEOF")

    def test_given_an_arithmetic_shift_when_checked_then_it_is_not_a_heredoc(self):
        self.denied("echo $((1<<2))\ngh issue close 5")
        self.denied("(( x = 1 << 2 ))\ngh issue close 5")

    def test_given_a_variable_as_gh_or_its_subcommand_when_checked_then_denied(self):
        self.denied("C=close; gh issue $C 5")
        self.denied("G=gh; $G issue close 5")
        self.denied('X="gh issue close 5"; eval "$X"')
        self.allowed('gh issue view "$n" --json state')

    def test_given_a_glued_short_label_flag_when_creating_then_denied(self):
        self.denied("gh issue create -t x -lsdd:no-red-green")

    def test_given_gh_api_input_from_stdin_when_writing_then_denied(self):
        self.denied("echo '{\"state\":\"closed\"}' | gh api -X PATCH repos/o/r/issues/5 --input -")
        self.denied("gh api -X PATCH repos/o/r/issues/5 --input - <<'EOF'\n{\"state\":\"closed\"}\nEOF")

    def test_given_a_hash_inside_a_word_when_checked_then_the_rest_still_counts(self):
        self.denied("echo issue#5 && gh issue close 5")

    def test_given_a_comment_line_when_checked_then_the_next_line_still_counts(self):
        self.denied("# note\ngh issue close 5")
        self.allowed("git status # never run gh issue close here")

    def test_given_a_graphql_update_issue_that_closes_when_checked_then_denied(self):
        self.denied(
            "gh api graphql -f query='mutation{updateIssue(input:{id:\"I\",state:CLOSED}){issue{id}}}'"
        )
        self.allowed("gh api graphql -f query='mutation{updateIssue(input:{id:\"I\",title:\"t\"}){issue{id}}}'")

    def test_given_a_get_with_fields_when_checked_then_allowed(self):
        self.allowed("gh api -X GET repos/o/r/issues -f state=closed")

    def test_given_a_shell_script_or_eval_in_a_variable_when_checked_then_denied(self):
        self.denied('bash -c "$X"')
        self.denied('A=1 eval "$X"')

    def test_given_a_shell_script_that_only_uses_variables_inside_when_checked_then_allowed(self):
        self.allowed("sh -c 'echo $HOME'")
        self.allowed('bash -c \'for f in *; do echo "$f"; done\'')
        self.denied('bash -c "${X}"')

    def test_given_read_only_gh_api_queries_when_checked_then_allowed(self):
        self.allowed("gh api 'repos/o/r/issues?state=closed'")
        self.allowed(
            "gh api graphql -f query='{ repository(owner:\"o\", name:\"r\") "
            "{ issues(labels:[\"sdd:stage:complete\"]) { totalCount } } }'"
        )


class SetStage(unittest.TestCase):
    """set-stage.py complete|verified needs a clean tree with a matching gate marker."""

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
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "first")

    def mark(self):
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        subprocess.run(
            [sys.executable, str(GATE_MARKER), "--repo", str(self.repo), "write", tree],
            check=True,
            capture_output=True,
        )

    def set_stage(self, stage, cwd=None):
        cmd = f"python3 .claude/skills/sdd-reconcile/scripts/set-stage.py 352 {stage}"
        return bash(cmd, cwd=str(cwd or self.repo))

    def test_given_no_marker_when_set_stage_complete_then_denied(self):
        self.assertIsNotNone(guard.decide(self.set_stage("complete")))

    def test_given_marker_on_clean_tree_when_set_stage_complete_then_allowed(self):
        self.mark()
        self.assertIsNone(guard.decide(self.set_stage("complete")))

    def test_given_marker_but_dirty_tree_when_set_stage_verified_then_denied(self):
        self.mark()
        (self.repo / "a.txt").write_text("changed\n")
        self.assertIsNotNone(guard.decide(self.set_stage("verified")))

    def test_given_no_marker_when_set_stage_implementing_then_allowed(self):
        self.assertIsNone(guard.decide(self.set_stage("implementing")))

    def test_given_cd_into_marked_worktree_when_set_stage_complete_then_checks_that_tree(self):
        self.mark()
        cmd = (
            f"cd {self.repo} && python3 "
            ".claude/skills/sdd-pr-validate/scripts/set-stage.py 352 verified"
        )
        self.assertIsNone(guard.decide(bash(cmd, cwd=self._tmp.name)))

    def test_given_stage_in_a_variable_when_set_stage_then_checked_like_complete(self):
        cmd = 's=complete; python3 .claude/skills/sdd-reconcile/scripts/set-stage.py 352 "$s"'
        self.assertIsNotNone(guard.decide(bash(cmd, cwd=str(self.repo))))

    def test_given_stage_in_any_letter_case_when_set_stage_then_checked(self):
        self.assertIsNotNone(guard.decide(self.set_stage("COMPLETE")))

    def test_given_cd_in_a_subshell_when_set_stage_complete_then_denied(self):
        # The subshell cd does not change the cwd, so the target worktree is unclear.
        self.mark()
        cmd = (
            f"(cd {self.repo} && true); python3 "
            ".claude/skills/sdd-reconcile/scripts/set-stage.py 352 complete"
        )
        self.assertIsNotNone(guard.decide(bash(cmd, cwd=self._tmp.name)))

    def test_given_cd_after_or_or_pushd_when_set_stage_complete_then_denied(self):
        self.mark()
        tail = " && python3 .claude/skills/sdd-reconcile/scripts/set-stage.py 352 complete"
        for head in (f"false || cd {self.repo}", f"pushd {self.repo}", 'cd "$WT"'):
            with self.subTest(head=head):
                self.assertIsNotNone(guard.decide(bash(head + tail, cwd=str(self.repo))))

    def test_given_cd_in_a_group_if_prefix_or_background_when_set_stage_complete_then_denied(self):
        self.mark()
        tail = "; python3 .claude/skills/sdd-reconcile/scripts/set-stage.py 352 complete"
        for head in (
            "{ cd /elsewhere; }",
            "if true; then cd /elsewhere; fi",
            "command cd /elsewhere",
            "builtin cd /elsewhere",
            "time cd /elsewhere",
            "nohup cd /elsewhere",
            "cd /elsewhere &",
        ):
            with self.subTest(head=head):
                self.assertIsNotNone(guard.decide(bash(head + tail, cwd=str(self.repo))))

    def test_given_set_stage_in_a_nested_shell_when_no_marker_then_denied(self):
        cmd = "bash -c 'python3 .claude/skills/sdd-reconcile/scripts/set-stage.py 352 complete'"
        self.assertIsNotNone(guard.decide(bash(cmd, cwd=str(self.repo))))

    def test_given_cwd_not_a_repo_when_set_stage_complete_then_denied(self):
        self.assertIsNotNone(guard.decide(self.set_stage("complete", cwd=self._tmp.name)))


class HookProtocol(unittest.TestCase):
    def test_given_raw_close_when_hook_runs_then_it_prints_a_deny_decision(self):
        code, out = run_hook(bash("gh issue close 1"))
        self.assertEqual(code, 0)
        output = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("close-sub-issue.py", output["permissionDecisionReason"])
        # The message names the shared script, not a repo-relative path.
        self.assertIn("close-sub-issue.py", output["permissionDecisionReason"])

    def test_given_allowed_command_when_hook_runs_then_it_prints_nothing(self):
        self.assertEqual(run_hook(bash("git status")), (0, ""))

    def test_given_malformed_input_when_hook_runs_then_it_prints_nothing(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))


AGENTS = HOOK.parent.parent.parent / "agents"
HOOK_BLOCK = (
    "hooks:\n"
    "  PreToolUse:\n"
    "    - matcher: \"Bash\"\n"
    "      hooks:\n"
    "        - type: command\n"
    "          command: 'python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/sdd_gate_guard.py\"'\n"
)


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    return text.split("---\n", 2)[1]


class AgentDeclarations(unittest.TestCase):
    """The hook is agent-scoped: declared in the SDD agents' frontmatter only."""

    def test_given_orchestrator_agent_when_read_then_it_declares_the_hook(self):
        self.assertIn(HOOK_BLOCK, frontmatter(AGENTS / "sdd-flow.md"))

    def test_given_stage_agent_when_read_then_it_declares_the_hook(self):
        self.assertIn(HOOK_BLOCK, frontmatter(AGENTS / "sdd-flow-stage.md"))

    def test_given_stage_agent_when_read_then_it_is_named_and_inherits_all_tools(self):
        # Same tools as general-purpose: no `tools:` allowlist, so it inherits every tool.
        fm = frontmatter(AGENTS / "sdd-flow-stage.md")
        self.assertIn("name: sdd-flow-stage\n", fm)
        self.assertIn("\ndescription: ", "\n" + fm)
        self.assertNotIn("\ntools:", "\n" + fm)

    # sdd-flow ships no settings.json of its own: the hook is declared only in agent
    # frontmatter (checked above), never at the plugin level. A consuming project's
    # own .claude/settings.json is outside the plugin and not sdd-flow's to check.

    def test_given_orchestrator_when_it_dispatches_a_stage_then_it_uses_a_guarded_agent(self):
        # The writer agents of workspace-agents.md also carry the hook; the other stages stay on sdd-stage.
        agent = (AGENTS / "sdd-flow.md").read_text(encoding="utf-8")
        dispatch = agent.split("## Subagent dispatch", 1)[1].split("\n### ", 1)[0]
        for row in ("| `sdd-flow-intent` | `sdd-flow-stage` |", "| `sdd-flow-reconcile` | `sdd-flow-stage` |",
                    "| `sdd-flow-pr-validate` | `sdd-flow-stage` |"):
            self.assertIn(row, dispatch)
        self.assertIn("Never dispatch a stage as another agent type", dispatch)
        self.assertNotIn("general-purpose", agent)


if __name__ == "__main__":
    unittest.main()
