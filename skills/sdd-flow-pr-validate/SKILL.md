---
name: sdd-flow-pr-validate
description: Use when sdd-flow-reconcile has marked a feature complete and it's time to validate before opening or merging a pull request.
---

# Spec-Anchored PR Validate

**Helper paths:** every script and template this skill uses is shared across the sdd-flow plugin, at `${CLAUDE_PLUGIN_ROOT}/scripts/…` and `${CLAUDE_PLUGIN_ROOT}/templates/…`. `${CLAUDE_PLUGIN_ROOT}` is the plugin's own install directory, set by the Claude Code plugin runtime; it resolves the same way regardless of where the plugin is installed.

## Overview
Final gate before PR: confirms the loop actually reached completion (not just "probably done"), re-runs the project's own governance checks, then gets the branch reviewed by **independent subagents** — never by the agent that wrote the code. A feature is `verified` only when both reviews come back clean.

**Violating the letter of this gate is violating its spirit.** Your own read of the diff is not a review.

## Steps

1. Resolve the main issue: `n=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-issue.py")`. On a non-zero exit, stop. Tell the user to run `sdd-flow-intent` or to check out the feature branch. Read `gh issue view "$n" --json labels,body` and the sub-issue summary:

   ```bash
   summary=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sub-issues-summary.py" "$n") || { echo "sub-issue summary failed" >&2; exit 1; }
   read completed total <<< "$summary"; [ -n "$completed" ] && [ -n "$total" ] || { echo "empty sub-issue summary" >&2; exit 1; }
   ```

   It prints `<completed> <total>` from the GraphQL `subIssuesSummary` and is read-only. Never read it through a process substitution that drops the exit status. A failed read leaves both values empty. Empty equals empty, so the `completed == total` check below would wrongly pass. A failed or empty summary is a stop, not a pass. The helpers are stdlib Python scripts in `${CLAUDE_PLUGIN_ROOT}/scripts/`; their tests run with `python3 -m unittest discover -s "${CLAUDE_PLUGIN_ROOT}/scripts"`. Keep dollar-plus-digit positional tokens (perl/shell capture references) out of this file: the skill loader substitutes the skill's arguments into them.

   **Refuse to proceed** — send it back to `sdd-flow-reconcile` — unless **all** of:
   - the label is `sdd:stage:complete`;
   - `completed == total` (with `total == 0` also acceptable);
   - the `## Open decisions` block has no unchecked `- [ ]` box (a lone `- [ ] _none_` is fine).
2. Locate the project's build-gate command from its governance docs (e.g. a "Build gate" line in `constitution.md`/`rules.md`/`CLAUDE.md`). If none is documented, ask the user once for the command and suggest they add it to the project's docs.
3. Run that build-gate command on a clean tree, after the last commit. Use the project's gate script if its docs name one (for example `scripts/check.sh`). On a pass from a clean tree, that script can write the gate marker `git rev-parse --git-path sdd-gate/<tree>`. Step 6 needs that marker on `HEAD^{tree}`: under the SDD agents a hook denies `set-stage.py "$n" verified` without it. It must pass before continuing. Then search the project's BDD feature files, if it has them, for a `@wip` tag (`git grep -n '@wip'` limited to those files). The build gate skips `@wip` scenarios, so a green gate does not show them. Each `@wip` tag still on the branch is a finding. Resolve it in step 5 with the review findings. The fix implements the scenario and removes its tag. Only the user can waive the finding. If the project has a spec linter (for example `scripts/check_spec_lint.py`), also run it with `--resolve-tests` (`python3 scripts/check_spec_lint.py --resolve-tests`). The build gate checks only the shape of a `[test: …]` tag, and this run checks that the named test exists. Each violation it prints is a blocking finding. The project may have a graph refresh script (for example `scripts/graphify_refresh.py`). If so, run `python3 scripts/graphify_refresh.py --full`. The review then reads every source directory.
4. **REQUIRED: independent review by subagents.** Launch both reviews below, in parallel, in one message. Both review the whole branch diff against `main` (`git diff main...HEAD`), not just the latest commit.
   - **Code review** — invoke the `code-review` skill. Set its target to the open PR number, or to the branch `sdd/<n>-<slug>` if no PR exists yet. It runs as a forked subagent and hunts correctness bugs.
   - **Spec-conformance review** — dispatch a fresh `sdd-flow-code-reviewer` subagent with the Agent tool (`subagent_type: "sdd-flow-code-reviewer"`). It is a read-only reviewer agent that the project defines in `.claude/agents/sdd-flow-code-reviewer.md`. If the project has no `sdd-flow-code-reviewer` agent, dispatch a fresh `general-purpose` subagent, with `model: "sonnet"` (a checklist comparison doesn't need the top model). Its prompt has these parts, in order:
     1. Role: "You are reviewing branch `sdd/<n>-<slug>` for conformance. You did not write this code. Report findings only; do not edit files, except the one findings file below."
     2. Inputs: the branch name, `git diff main...HEAD`, the touched spec section(s) (the `**Spec files:**` paths) and the findings path (see **Findings in files**). If the project has them, also include the touched modules' rules files (e.g. a per-module `RULES.md`). If it has one, also include the project's constitution/non-negotiables (e.g. `constitution.md`).
     3. Checks: each behaviour in the touched spec section has an implementation **and** an executable BDD scenario in the project's tests. No behaviour is implemented that the spec doesn't describe. No blocklist item from a touched rules file is used (if the project has them). No constitution non-negotiable is violated (if the project has one).
     4. Red check: read each `test:` red commit of each sub-issue (its subject ends with `(#<child>)`). Report a weak or fake red as a non-blocking finding. A weak or fake red is a test that cannot fail, or a test that fails for an unrelated reason.
     5. Output: the findings go to the findings file below. Each finding has `file:line`, the rule or spec clause broken, and a concrete failure scenario. The reply is one line, `<N> findings -> <path>`, or `NONE`.

   **Findings in files.** Each review writes its findings to a file in `$(git rev-parse --git-path sdd-reviews)`. That is the per-worktree git directory, so no commit holds the files. A file is named `<n>-r<round>-<code-review|spec-conformance>.txt`, where `<n>` is the number of the main issue. Give the path in the prompt of the review. The conformance reviewer creates the directory with `mkdir -p`, writes the file and returns one line, `<N> findings -> <path>`, or `NONE`. The `code-review` skill does not write a file. Outside the orchestrator, the agent that ran it writes the code-review findings file. It first creates the directory with `mkdir -p`. A fix reads a findings file only by line range (`sed -n`, `grep -n`), never the whole of a large file.

   Wait for **both** results. Never predict, summarize ahead of, or assume a pending result.

   If the Agent tool or the `code-review` skill is unavailable in this session, **stop**: tell the user which one is missing. Do not replace it with your own review. **Exception — orchestrator subagent:** do not stop if your dispatch prompt gives a `NEEDS_REVIEWS` block format. Instead, end your turn with a `NEEDS_REVIEWS` block, in the format your dispatch prompt gives. List the branch, the diff range, the touched spec sections, the touched rules files and the constitution. List each only if the project has it. The orchestrator runs the reviews as independent subagents. It sends the one-line results and the findings paths to a fresh subagent. A `NEEDS_REVIEWS` block ends your turn, and that subagent is not resumed. The fresh subagent starts at step 5 (see below).
5. **Resolve every finding** from both reviews before going further. Record `base=$(git rev-parse HEAD)` before fixing anything. Each finding ends in exactly one of:
   - **Fixed**: commit the fix on the `sdd/<n>-<slug>` branch (`fix: …`). Fix **all** findings from the round first. Then run the build gate (step 3) once. Then re-run each review that raised a finding, **once for the whole batch**. Do not re-run a review per individual finding.
   - **Waived by the user**: only the user can waive a finding. You cannot waive one yourself, however minor it looks. The user waives at the question after round 2 (below). The audit trail records the reason as "waived by the user at the round <k> question".

   The `sdd-flow-code-reviewer` agent tags each finding `blocking:` or `follow-up:`. In this stage the tag changes nothing: each finding with either tag is fixed or waived by the user. A non-blocking red finding needs no fix or waiver before `verified`. Put it in the audit trail as `non-blocking`. Only a weak or fake red from the red check (item 4) is a non-blocking red finding. A `follow-up:` tag does not make a finding non-blocking.

   **Round cap.** The loop runs at most two review rounds. Round 1 is the first pair of reviews (step 4). Round 2 is one re-review of the fix commits of round 1. Each later round has the next number. A run never starts a round 3 by itself.
   - **Narrow re-review.** Only a review that raised a finding in the previous round runs again, so its `N` is at least 1. Return `NEEDS_REVIEWS` with `diff: <base-sha>..HEAD`, `code-review effort: low` and the findings being re-checked. The conformance reviewer gets the same range and the prior findings. Its brief reads: `confirm these N findings are fixed; report only defects that lines in this diff introduce`. Do not re-run a review that came back clean.
   - **Fresh fix subagent.** A fix round starts in a fresh subagent. The orchestrator gives it the branch, the worktree and the base SHA. It also gives the round number, the findings paths and the path of the audit file `<n>-audit.txt`. That file holds the audit lines so far. The subagent starts at step 5. It reads the findings files by line range. Then it fixes and runs the build gate. It adds one audit line per fix to the audit file: `file:line` — fix in `<sha>`. Then it ends with `NEEDS_REVIEWS` for the re-review. Each later subagent reads the audit lines from that file. A fix is not confirmed until a re-review does not report its finding again. In the audit trail, a confirmed fix is `fixed in <sha>`, and a finding that is still open is open or waived. A subagent that receives clean results does the audit trail and steps 6 and 7.
   - **Question after round 2.** After the re-review of round 2, a finding may still be open. Then the subagent that received those results ends its turn with one `NEEDS_INPUT` block. After a re-review that follows a `continue`, the same question comes again. The block has three options:
     - continue (one more fix round and one more re-review);
     - waive all open findings and file one follow-up issue for each;
     - stop.
   - **Outside the orchestrator.** Ask the user the same question directly, in place of the `NEEDS_INPUT` block.
   - **Answer.** The orchestrator resumes the subagent with the answer. On `continue`, fix, add the audit lines, run the build gate and end with `NEEDS_REVIEWS`.
   - **On `waive`.** File one follow-up per open finding with `create-follow-up.py`. Read the finding by line range; it can have more than one line. Write its title (`file:line` and the rule) and its full text to two files, each with a quoted heredoc (`<<'EOF'`). Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-follow-up.py" "$n" --title "$(cat <title file>)" --finding "$(cat <finding file>)"`. Do not paste the title or the finding into the command. A backtick or a dollar sign in them is shell syntax. Then post the audit trail and do steps 6 and 7.
   - **On `stop`.** Post the audit trail with the open findings. The run leaves the stage at `complete`, so do not set `verified`. Report `DONE` with the line `outcome: stopped by the user`.

   Post the audit trail on the main issue: `gh issue comment "$n" --body-file <file>`. Give one line per review: which review, clean or N findings. Give one line per finding: `file:line` — fixed in `<sha>` / waived by the user at the round <k> question.
6. Move the issue to stage `verified`. If the project has a merge / worktree-teardown script, it treats `verified` as its precondition. Skipping this step blocks that script:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" verified
   ```

   It swaps every other `sdd:stage:*` label for `sdd:stage:verified` and rewrites the `**Stage:**` body line to match. It reads and writes UTF-8 and refuses to write an empty body. Then it re-reads the issue. A non-zero exit means the label or the body did not land as intended. Stop. Do not retry blindly. Report the failure. Never hand-edit the body with `perl`/`sed`: either can silently corrupt non-ASCII characters elsewhere in the body.
7. Push the branch and make sure a PR exists: `gh pr view` it, or create it with `gh pr create --base main`. The PR body must contain `Closes #<n>` so the main issue closes on merge.

## Red Flags — STOP, you are skipping the review gate

| Thought | Reality |
|---|---|
| "I wrote it and I've read the diff — that's a review." | The author can't see their own blind spots. Only a subagent review counts. |
| "The build gate is green, so a review is redundant." | Tests only cover what someone thought to test. The review looks for what they didn't. |
| "The diff is tiny / just docs / just a fix." | Every branch gets both reviews. Size is not an exemption. |
| "That finding is minor, I'll note it and move on." | Fix it or have the user waive it. There's no third option. |
| "The review is still running; I'll mark `verified` now." | `verified` comes after both results are in and every finding is resolved. |
| "The subagent tool isn't here, so I'll review it myself." | Stop and tell the user — or, as an `sdd` orchestrator subagent, return `NEEDS_REVIEWS`. A self-review is not a substitute. |
| "I fixed the finding; no need to re-review." | Fixes introduce bugs. Re-run the review that raised it. |

## Common Mistakes
- Running the build gate before checking the main issue's state. A green build gate on an incomplete feature is not readiness.
- Reading the wrong issue because the branch isn't `sdd/<n>-<slug>` — if `n` comes back empty, stop; do not guess an issue number.
- Reviewing only the last commit instead of `main...HEAD`: bugs from earlier tasks on the branch go unseen.
- Swapping the label to `sdd:stage:verified` with findings still open, or never swapping it at all. Then nothing downstream can tell this feature passed validation, and worktree teardown tooling will refuse to run.
