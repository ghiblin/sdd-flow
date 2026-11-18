---
name: sdd-flow-merge-pr
description: Squash-merge a verified SDD feature's PR and tear down its worktree/branch. User-triggered only — never run this on your own.
argument-hint: [worktree-name] [--dry-run] [--skip-ci-check] [--repo OWNER/REPO]
disable-model-invocation: true
---

# Merge PR and tear down worktree

This is the manual, user-confirmed finish line for a feature validated by `sdd-flow-pr-validate`: it squash-merges the PR, deletes the branch, removes the worktree, and closes the feature's main issue. Only run it because the user just typed `/sdd-flow:sdd-flow-merge-pr`, never on your own initiative.

## Steps

1. If `$ARGUMENTS` is empty, don't guess a worktree name. List `.claude/worktrees/` and ask the user which one to merge.
2. Run the shared script, passing through whatever was typed after the command:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/merge_pr.py" $ARGUMENTS
   ```

3. Show the script's output to the user as-is. On a non-zero exit, stop and report the error — don't retry or work around the refusal (e.g. a not-yet-`verified` stage gate, or open sub-issues) without the user's say.
