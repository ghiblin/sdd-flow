---
name: sdd-flow-tdd
description: Use when implementing a feature under the SDD workflow, after sdd-flow-draft has written the minimal spec section and before any implementation code is written.
---

# Spec-Anchored TDD

**Helper paths:** most scripts and templates this skill uses are shared across the sdd-flow plugin, at `${CLAUDE_PLUGIN_ROOT}/scripts/…` and `${CLAUDE_PLUGIN_ROOT}/templates/…` (the plugin's own install directory, set by the Claude Code plugin runtime). `remove-wip.py` is specific to this skill and lives at `<base>/scripts/remove-wip.py`, where `<base>` is this skill's own base directory (the path on the `Base directory for this skill:` line the skill loader prints above this text).

## Overview
Implements the drafted spec section via TDD, one **open sub-issue** at a time, with BDD scenarios living as real test code (not spec prose), and a continuous human-in-the-loop split between trivial and significant decisions.

**REQUIRED BACKGROUND:** superpowers:test-driven-development — this skill adds the BDD-scenario and human-in-the-loop layers on top of that RED-GREEN-REFACTOR cycle; it doesn't replace it.

## The rule

**No implementation code before a failing BDD-style test exists for it.** Given/When/Then scenarios are written as actual test functions, in the project's test suite, not as prose in the spec file. The spec section carries no **Tests** heading — the test files are discovered directly under the project's test directories.

**Drafted scenarios come first.** When the project has BDD feature files, `sdd-flow-draft` already wrote the section's scenarios there, tagged `@wip`, with pending step stubs. The project's build gate skips `@wip` scenarios. You implement those scenarios; you do not write new ones in their place. Remove the `@wip` tag in the same commit that makes the scenario pass. Step 7 removes it with `remove-wip.py`.

**Scenario changes need approval.** A drafted scenario that is wrong, or a scenario the section needs that the draft does not have, is a significant decision. Record the question in `## Open decisions` (step 4) and ask the user. After the user approves, do not edit the feature file yourself. The test author stays separate from the implementer, so a fresh `sdd-flow-draft` writer changes or adds the scenario. Under the `sdd` orchestrator (when your dispatch prompt gives a `NEEDS_SCENARIO_CHANGE` block format), make the worktree clean first. Save your uncommitted work, except feature files, as a patch in the git directory of this worktree. Run `git add -A -- ':/' ':(top,exclude,glob,icase)**/*.feature'`, then `git diff --cached --binary -- ':/' ':(top,exclude,glob,icase)**/*.feature' > "$(git rev-parse --git-dir)/sdd-wip-<child>.patch"`, then `git reset -q --hard`. The `:/` pathspec covers the whole worktree from any directory. The exclude on the diff also leaves out a feature file change that was already staged. The reset also drops the uncommitted `@wip` removals of `remove-wip.py`. Each worktree has its own git directory, so no other worktree can apply or take the patch. Do not use `git stash`: its list is shared by all worktrees. Then end your turn with that block. It names the sub-issue, the feature file and the change that the user approved. The orchestrator gets the change written, then sends you `SCENARIO CHANGED: <commit sha>`. If you saved a patch, apply it with `git -C "$(git rev-parse --show-toplevel)" apply --3way "$(git rev-parse --git-dir)/sdd-wip-<child>.patch"`. If the apply conflicts, resolve each conflict first, and keep the patch until you have. Run it from the top of the worktree: `git apply` in a subdirectory skips the paths outside it. The patch has no feature file in it, so a conflict can only be in a file that you can edit. Then run `git reset -q` and delete the patch. Run `remove-wip.py` again for each scenario whose tag you removed before the reset. Do not run it for a scenario that the change renamed or changed: that scenario keeps `@wip` until step 7. Then continue from step 5 for that scenario. A changed or added scenario keeps `@wip` until step 7 removes the tag to implement it.

**Each development increment is one `sdd:task` sub-issue of the feature's main issue.** It stays open until its implementation lands and the build gate passes, then it is closed.

**Significant decisions are discussed before proceeding; trivial ones are made autonomously.**

- Significant: a public API/trait signature, a constitution non-negotiable, a data/schema shape or a cross-module boundary. Discuss it with the user before you continue. The project's `constitution.md` (or equivalent) lists the non-negotiables.
- Trivial: internal helper structure, naming, or a pattern already established elsewhere in this codebase. Decide it yourself without stopping.
- A change to a drafted scenario is also significant (see the rule above).

## Rationalization table

| Excuse | Reality |
|---|---|
| "I'll write the test right after, it's basically the same" | Test-after answers "what does this do", test-first answers "what should this do" — write it first. |
| "We already discussed something similar earlier" | Similar isn't identical. A genuinely new public signature or schema shape is a new significant decision even if the pattern rhymes. |
| "Stopping to ask breaks my flow" | The workflow is designed for exactly this pause — see sdd-flow-reconcile, this isn't a detour, it's the loop. |
| "Time is short, ship it now, clean up later" | Time pressure is exactly when public-shape mistakes get baked in. The check-in costs one message; the mistake costs a reconcile-loop later. |
| "I can't literally block for a reply right now, so I'll implement my best guess and label it 'provisional'/'draft' in the spec or code comments" | Not being able to wait synchronously doesn't remove the check-in — it changes its shape. The check-in IS stopping before implementation code exists and presenting the question as your output. Implementing the guess and captioning it "unconfirmed" afterward is shipping the guess, not asking. |

## Red flags — stop and start over

- Implementation code exists with no corresponding failing test committed first.
- A new public function/trait/schema field got added without a check-in, because "it seemed small."
- The BDD scenario got written as a bullet in the spec file instead of a test function.
- A significant decision got implemented, then flagged "provisional," "draft," or "not yet confirmed" in a comment or spec note. It had to be a question, asked before any code for it was written.

## Creating a sub-issue

`$n` is the main issue number (step 1). Create the child and nest it under the main issue in one command:

```bash
child=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-sub-issue.py" "$n" --title "<increment description>")
```

For a group of drafted `@wip` scenarios, add one `--scenario "<scenario name>"` per scenario. The body then names them under a `Scenarios:` line, each as a code span, so an `@name` or `#123` in a name neither notifies nor links. A blank scenario name is refused.

The script creates the issue with the `sdd:task` label and a `Part of #$n` body (from `${CLAUDE_PLUGIN_ROOT}/templates/sub-issue.md`), nests it with the GraphQL `addSubIssue` mutation, then re-reads the main issue's sub-issues. A non-zero exit naming a child means the child exists but is not nested — report the un-nested child rather than dropping it.

## Steps

1. **Resolve the main issue.** `n=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-issue.py")`. On a non-zero exit, stop. Tell the user to run `sdd-flow-intent` or to check out the feature branch. Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n"`. It prints the open sub-issues that carry `sdd:needs-spec`: their behaviour is not in the spec section yet. If it prints any number, stop. Do not start a sub-issue. Tell the user that the next stage is `sdd-flow-draft` for those sub-issues. Then read the stage label with `gh issue view "$n" --json labels`. If it is `sdd:stage:drafting-spec`, stop: the user has not approved the spec section. Tell the user that the next stage is `sdd-flow-draft`, which ends at the approval. If it is `sdd:stage:spec-approved`, move the issue to `implementing`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" implementing
   ```

   The script refuses from any other label and keeps the label. Report a refusal. Any later label (`implementing` or `complete`) needs no change.
2. **Get the work list.** List the main issue's sub-issues, one `number<TAB>STATE<TAB>title` line each (add `--open` for only the open ones):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/list-sub-issues.py" "$n"
   ```

   If there are **no** sub-issues yet (empty output), create them with the create+nest command above. If the project's BDD feature files hold `@wip` scenarios, make one sub-issue per group of `@wip` scenarios, and name them with `--scenario`. Otherwise, make one per unbuilt piece of the section's **Decisions** / **Architecture**.
3. Take the next **open** sub-issue from that list. Call its number `$child`. (The `## Creating a sub-issue` helper also sets `$child` when it makes a new one.)
4. Classify it trivial or significant per the table above. If it is significant, present the choice and its trade-off to the user. Wait for their answer before you write any code for it. Also append the question to the main issue's `## Open decisions` block so a cleared session sees it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "<question>"
   ```

   The script replaces the `- [ ] _none_` placeholder, or it appends a new `- [ ] <question>` line inside the block. It skips the write if that exact question is already in the block. That is, open, or resolved as `- [x] <question>` / `- [x] <question> → <decision>`. It refuses `_none_` and questions containing `→`. It reads and writes UTF-8 and refuses to write an empty body. Thus em dashes, arrows and accented names elsewhere stay intact. Then it re-reads the issue. A non-zero exit means the edit did not land. Stop. Do not retry blindly. Report the failure. Keep dollar-plus-digit positional tokens (perl/shell capture references) out of this whole file. The skill loader substitutes the skill's arguments into them. The shared scripts' tests run with `python3 -m unittest discover -s "${CLAUDE_PLUGIN_ROOT}/scripts"`; `remove-wip.py`'s test runs with `python3 -m unittest discover -s "<base>/scripts"`.
5. Get a failing BDD scenario for each behaviour of the sub-issue.
   - For a drafted scenario in the project's BDD feature files: Replace the pending step stubs with real step definitions. Run it the project's way to run only `@wip` scenarios. Step 6 must show that it fails for the expected reason: missing behaviour, not a pending stub. Remove its `@wip` tag in step 7, with the code that makes it pass.
   - With no drafted scenario: write the BDD scenario as a failing test. Use Given/When/Then as setup/act/assert, or your framework's native BDD style.
6. Run it. Confirm that it fails for the expected reason. Then commit only the failing test, as `test: <description> (#<child>)`. A drafted scenario is still tagged `@wip` in this red commit. The red commit is the only commit that can fail the build gate. A sub-issue with the `sdd:no-red-green` label has no behaviour to test first, so it has no red commit. Only `sdd-flow-draft` sets this label, after the user approves it.
7. Write the minimal implementation to pass it. For each drafted scenario of the sub-issue, remove its `@wip` tag with `python3 "<base>/scripts/remove-wip.py" <feature file> --scenario "<scenario name>"`. Give one `--scenario` per scenario. The script removes only the `@wip` tag of each named scenario and changes nothing else in the file. A non-zero exit means that it changed nothing. Its message gives the reason. Never remove the tag by hand. Commit the removed `@wip` tag with the code, as `feat: <description> (#<child>)`. For a bug fix, use `fix: <description> (#<child>)`.
8. Run it. Confirm that it passes. Then run the project's full build gate (from its governance docs, e.g. `constitution.md`/`rules.md`/`CLAUDE.md`) on a clean tree, after the commit. Use the project's gate script if it has one. On a pass from a clean tree, that script writes the gate marker `git rev-parse --git-path sdd-gate/<tree>`. If the gate fails, commit the correction for `(#<child>)` as one more `feat:` or `fix:` commit. Then run the gate again.
9. Get the commits of the sub-issue reviewed (see **Code review**). The project may have a new public item check (for example `scripts/check_pub_items.py --issue "$n"`). If so, run it before the close. On exit 1, report each printed `UNRESOLVED` item. Keep the sub-issue open until a checked `- [x]` line in `## Open decisions` resolves each one. Then close it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/close-sub-issue.py" "$n" "$child"`. The script refuses unless the tree is clean and a gate marker matches `HEAD^{tree}`. Unless the sub-issue has `sdd:no-red-green`, it also needs a `test:` commit before a `feat:` or `fix:` commit for `(#<child>)`. A non-zero exit means the sub-issue is still open. Its message gives the reason. Correct the cause, for example with a new gate run. Never close it another way. Under the SDD agents, a hook denies a raw issue close.
10. Repeat from step 3 until every sub-issue is closed, or until reconcile finds something new to add. **Session budget:** if context is past ~150k tokens when a sub-issue closes, do not start the next sub-issue. Instead, run `sdd-flow-reconcile`. After it, hand off to a fresh session. Never stop mid-sub-issue for this.

## Code review

Only under the `sdd` orchestrator: when your dispatch prompt gives a `NEEDS_CODE_REVIEW` block format, a read-only code reviewer checks each sub-issue before it closes. Each sub-issue has one loop of at most two review rounds.

- After the build gate of step 8, and before step 9 closes the sub-issue, stop for a review. End your turn with a `NEEDS_CODE_REVIEW` block. Use the format that your dispatch prompt gives. Its commit range starts at the red commit of the sub-issue (or at its first commit, for a sub-issue with `sdd:no-red-green`). The results come back in a message that starts with `CODE REVIEW RESULTS:`.
- Each finding is tagged `blocking:` or `follow-up:`. Fix each blocking finding. Commit each fix. Use one more `feat:` or `fix:` commit for `(#<child>)`. Do not close the sub-issue while a blocking finding is open.
- File each follow-up finding as an issue with `create-follow-up.py`: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-follow-up.py" "$n" --title "<title>" --finding "<finding text>"`. A follow-up finding never blocks the close. In round 2, file only a follow-up finding that round 1 did not file.
- Ask for round 2 only if round 1 had a blocking finding. Round 2 gives the prior findings to re-check, the follow-up findings already filed and the new commits. Never ask for a round 3.
- After round 2, record each blocking finding that is still open as an `## Open decisions` question with the step 4 script. Ask the user with one `NEEDS_INPUT` per finding. Apply the answer of the user, and do not ask for another review.
- Do step 9 only when no blocking finding is open. If fix commits landed after the step 8 gate, first run the build gate again on the clean tree. Without fix commits, the step 8 gate marker still matches the tree.

**Sizing sub-issues:** when step 2 creates sub-issues, size each so it fits comfortably in one session: a handful of RED-GREEN cycles touching one or two modules. Split anything larger.

## Common Mistakes
- Writing a new scenario next to a drafted `@wip` one instead of implementing the drafted one. Or editing a drafted scenario without the user's approval.
- Leaving the `@wip` tag on a scenario that passes. Then the build gate never runs it.
- Editing a feature file yourself, for a tag or for an approved scenario change. Use `remove-wip.py` for the tag. Hand a scenario change to `sdd-flow-draft`.
- Batching several significant decisions into one check-in to save the user's time. Ask about each one as it comes up: batching hides their trade-offs from each other.
- Committing the test and the code together. Then no `test:` commit comes before the `feat:` commit, and `close-sub-issue.py` refuses the close.
- Building a piece with no `sdd:task` sub-issue to track it. Create the sub-issue first, nested under the main issue (step 2), so `sdd-flow-reconcile` and `sdd-flow-pr-validate` can see the work.
- Rewriting an issue body by hand with `perl -0pe` or `sed`. Depending on locale, either can silently corrupt non-ASCII characters elsewhere in the text. Use the step 4 script instead: it edits UTF-8 explicitly and verifies the read-back.
