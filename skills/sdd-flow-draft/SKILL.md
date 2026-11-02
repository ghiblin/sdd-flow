---
name: sdd-flow-draft
description: Use when the sdd-flow-intent step has resolved a target spec file and it's time to write or amend the living spec section for that intent, before implementation starts.
---

# Spec-Anchored Draft

**Helper paths:** every script and template this skill uses is shared across the sdd-flow plugin, at `${CLAUDE_PLUGIN_ROOT}/scripts/…` and `${CLAUDE_PLUGIN_ROOT}/templates/…`. `${CLAUDE_PLUGIN_ROOT}` is the plugin's own install directory, set by the Claude Code plugin runtime; it resolves the same way regardless of where the plugin is installed.

## Overview
Amends a living per-module spec file in place for the current intent — a short, current section, not a growing history of every feature that ever touched the module.

When the project has BDD feature files, the drafting session also writes the intent's scenarios there, tagged `@wip`. The scenarios fail until `sdd-flow-tdd` implements them, so the test author is not the implementer.

Public interface signatures and test-file paths are not standing headings: signatures drift fast and are better read from the code, and test files are discoverable directly under the project's test directories. The spec section captures what stays stable — goal, architecture, and decisions.

## Section template

Append (new module) or amend (existing module, same heading) this exact structure in the spec file named on the issue's `**Spec files:**` line (`docs/specs/<module-slug>.md`, or `docs/specs/<topic>/<module-slug>.md` if the project groups specs into topic folders — follow its documented folder rule):

````markdown
## <Concept name, e.g. "Router">

**Goal:** <1-2 sentences: what this achieves and why>

**Architecture:** <1-3 sentences: how it fits — module/component boundaries, request/data flow, key file paths/commands>

**Out of scope:** <what this intent leaves out, or `none`>

**Criteria:**
- <When|While|Where|If <condition>, <subject> shall <behaviour>. [scenario: <feature path>: <scenario name>]>
- <When|While|Where|If <condition>, <subject> shall <behaviour>. [test: <path>::<test name>]>

**Decisions:**
- <key invariant or design decision worth remembering, one bullet each>
````

Omit the **Decisions** heading entirely if a concept genuinely has zero noteworthy decisions — don't leave it empty.

Write **Criteria:** for a new or amended section. Each criterion is one bullet in the EARS form `When|While|Where|If <condition>, <subject> shall <behaviour>.` It ends with exactly one tag. Use `[scenario: <feature path>: <scenario name>]` when a BDD scenario covers it, or `[test: <path>::<test name>]` for a named test. Avoid vague words such as "appropriate" and "should", and leave no behaviour open. A spec linter, if the project has one, checks these rules. Commit the spec before it runs.

Always write **Out of scope:** for a new or amended section. `none` is a valid value. The line shows the reviewer the scope limits of the intent, and the validator flags behaviour built outside them.

## Steps

0. **Resolve the main issue.** `n=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-issue.py")`. If it exits non-zero, stop: the session is not on an `sdd/<n>-<slug>` branch. Tell the user to run `sdd-flow-intent` or to check out the feature branch. Read the issue with `gh issue view "$n" --json number,title,body,labels`. Check the stage note first: these three cases come before every case below.
   - If the stage note starts with "Approval resume", the user approved that draft. Check off each open approval line with a lower `k` with the resolution `superseded`. Then do only the approval commands at the end of step 7, with that `k`. Do nothing else.
   - If the stage note starts with "Scenario change for sub-issue", follow only **Scenario change** below.
   - If the stage note contains "The user requested these changes", this is a "Request changes" repeat. Before you write anything, check off the open approval line with the highest `k` as `changes requested` (see step 7). Check off each lower open approval line with the resolution `superseded`. Then go on below.

   Then list the open `sdd:needs-spec` sub-issues with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n"`. If it prints any number, follow **Scoped mode** below for those sub-issues. If the stage note contains "Scoped draft repeat", follow **Scoped mode** for the sub-issues that this sentence names. Other issue numbers in the note are not part of the scope. This is a "Request changes" repeat of a scoped draft: the first scoped draft cleared their labels already. A scoped draft can stop after it cleared the labels. Then the stage is still `drafting-spec`, `needs-spec.py` prints no number, and `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/list-sub-issues.py" "$n" --open` lists a sub-issue. In that case, ask the user to confirm the `Scenarios:` list of each open sub-issue. Read each list with `gh issue view <child> --json body`. Correct a wrong list with the `--clear` command of **Scoped mode**. After the user confirms, do only steps 6 and 7. A "Request changes" repeat in that state has no "Scoped draft repeat" note. It first does steps 1 to 5 for the whole section with the requested changes. Then it asks for that confirmation and does steps 6 and 7. A first draft (no sub-issues yet) runs as before.
1. From the issue body block (between `<!-- sdd:begin -->` / `<!-- sdd:end -->`), read `**Intent:**`, `**Worktree:**`, `**Branch:**`, and `**Spec files:**`. `**Spec files:**` is comma-separated — repeat steps 3-4 below for **every** path in it, not just the first. If drafting needs a spec file that the line does not list, add it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-spec-files.py" "$n" --add --spec-file <path>`. Only that line changes. A non-zero exit means the read-back did not match.
2. **Always draft in the feature's worktree — never on the main branch or the main checkout.** The issue body's `**Worktree:**` line is the repo-relative worktree path that `sdd-flow-intent` recorded. Its `**Branch:**` line is the exact branch name (`sdd/<n>-<slug>`) to use: do not invent one. **REQUIRED SUB-SKILL:** use `superpowers:using-git-worktrees` to ensure that worktree exists on the branch named in the issue body (`sdd/<n>-<slug>`). If it is absent, create it from the current main branch. Do the rest of this skill from inside it. If this session is already confined to that worktree, just confirm the path matches. Every `**Spec files:**` path below is relative to the worktree checkout, and every file edit in this skill happens there.
3. For the current spec file: if the file doesn't exist yet, create it with the concept's heading. If the file exists and already has a heading for this concept, amend that heading in place. Do not append a second heading for the same concept. Do not keep old **Decisions** bullets that the new intent supersedes: edit them, don't just add more. If the file exists but has no heading for this concept yet, a different concept already lives there. Append a new heading for this concept to the existing file. This is not the frozen-per-feature-file pattern. It is a genuinely new concept that shares a module file, not a repeat of one already documented. The project's governance docs may cap a spec file's size. If so, check the file against that cap before writing. When the new or amended section would push it over, first split the file the way those docs prescribe. Add every new file to `**Spec files:**` with `set-spec-files.py --add`.
4. Fill in **Goal** and **Architecture** now, before code exists — best-guess is fine, both get corrected at reconcile if reality diverges. Add **Decisions** bullets as they firm up. If no decision is firm yet, leave out the heading.
5. **Write the executable spec.** If the project has no BDD feature files, skip this step.
   - Write one scenario per behaviour that the section adds or changes, in the project's BDD feature files.
   - Tag each new scenario `@wip`, and each changed scenario that fails today. The project's build gate skips `@wip` scenarios. A changed scenario that still passes stays untagged, so the build gate keeps running it. Only `sdd-flow-tdd` removes the `@wip` tag.
   - For a step with no definition yet, add a step-definition stub that fails with a pending message. Then the scenario fails and is not skipped. A stub must not match the text of any step in a scenario without `@wip`.
   - Run only the `@wip` scenarios, the project's way. Confirm that each one fails.
   - Run the project's full build gate. Confirm that it still passes.
   - Commit the spec section and the feature files on the feature branch.
   - Then get the draft reviewed (see **Spec review**).
6. Once every `**Spec files:**` path is handled and **Spec review** has no open blocking finding, finish the draft. First apply **Red-green exemption** to each approved exempt sub-issue. In scoped mode, first clear the label on each drafted sub-issue (see **Scoped mode**). Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n"` again. Confirm that it prints no number.
7. **Get the approval.** The stage moves on only after the user approves the section. Add the approval line to `## Open decisions`. Take `k` one above the highest `k` present in lines of the form `Approve the spec section? (draft <k>)`, and 1 for a first draft:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "Approve the spec section? (draft <k>)"
   ```

   Ask the user exactly that question. Do not go on before the user answers. Under the `sdd` orchestrator, end your turn with a `NEEDS_INPUT` for it, as your dispatch prompt describes. The orchestrator shows the user the diff of the draft before it relays the question. A "Request changes" answer repeats the draft. Before it writes anything, step 0 of the repeat checks off the open approval line with the highest `k` with `changes requested`. Each lower open line gets `superseded`. Then its step 7 adds a new line with the next `k`:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check-open-decision.py" "$n" --question "Approve the spec section? (draft <k>)" --resolved-as "changes requested"
   ```

   Never check off the approval line before the user answers. Never write an approval that the user did not give. After the user approves, check the line off with the resolution `approved`. Then set the stage:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check-open-decision.py" "$n" --question "Approve the spec section? (draft <k>)" --resolved-as "approved"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" spec-approved
   ```

   The script refuses unless the highest-numbered approval line is checked with the resolution `yes` or `approved`. It swaps the `sdd:stage:*` label and rewrites only the `**Stage:**` line. It reads and writes UTF-8 and refuses to write an empty body. Thus em dashes, arrows and accented names elsewhere stay intact. Then it re-reads the issue. A non-zero exit means the approval, the label or the body did not land. Stop. Do not retry blindly. Report the failure. This skill never sets `implementing`: `sdd-flow-tdd` does, from `spec-approved`. The scripts' tests run with `python3 -m unittest discover -s "${CLAUDE_PLUGIN_ROOT}/scripts"`.

## Spec review

Only under the `sdd` orchestrator: when your dispatch prompt gives a `NEEDS_SPEC_REVIEW` block format, three read-only spec reviewers check the draft before the stage moves on. Each draft has one loop of at most two review rounds. A "Request changes" repeat and a scoped draft each start a new loop with its own two rounds. A scenario change has no spec review.

- Before your first commit of the draft, record `git rev-parse HEAD` as `<base-sha>`. The diff range of the block starts there.
- After step 5 commits the spec and the `@wip` scenarios, and before step 6 finishes the draft, stop for a review. End your turn with a `NEEDS_SPEC_REVIEW` block. Use the format that your dispatch prompt gives. If the project has no BDD feature files, commit the spec section first. The results come back in a message that starts with `SPEC REVIEW RESULTS:`.
- Each finding is tagged `blocking:` or `follow-up:`. Fix each blocking finding. Commit each fix. Do not ask for the approval while a blocking finding is open.
- File each follow-up finding as an issue with `create-follow-up.py`: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-follow-up.py" "$n" --title "<title>" --finding "<finding text>"`. A follow-up finding never blocks the stage. In round 2, file only a follow-up finding that round 1 did not file.
- Ask for round 2 only if round 1 had a blocking finding. Round 2 gives the prior findings to re-check, the follow-up findings already filed and the new commits. Never ask for a round 3.
- After round 2, record each blocking finding that is still open as an `## Open decisions` question with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "<question>"`. Ask the user with one `NEEDS_INPUT` per finding. Apply the answer of the user, and do not ask for another review.
- When no blocking finding is open, do steps 6 and 7.

## Scenario change

`sdd-flow-tdd` never edits a feature file. When the user approves a new or changed scenario during `sdd-flow-tdd`, a fresh session of this skill writes it. Its stage note is "Scenario change for sub-issue #<child>: <approved change>". In this mode:

- Change or add only the scenario that the note names, in the feature file that it names. Do not change the spec section. Create no sub-issue.
- Follow the rules of step 5. Keep or add its `@wip` tag. Add any step-definition stub that fails with a pending message.
- Run the project's full build gate. Confirm that it still passes.
- Commit only that change, as `test: <description> (#<child>)`.
- Do not ask for a spec review, and do not change the stage. Then report `DONE`.

## Scoped mode

A `sdd-flow-reconcile` pass can add work that the spec section does not describe yet. It marks each piece of that work as an open `sdd:task` sub-issue with the `sdd:needs-spec` label, and sets the stage `drafting-spec`. Step 0 finds these sub-issues. When it finds any, this session drafts only them:

- Write the behaviour of those sub-issues, and of the decisions they name, into the section. Read each sub-issue and the resolved lines in `## Open decisions` to find that behaviour.
- Follow the rules of step 3. Amend the section in place. Edit the **Decisions** bullets that the new behaviour supersedes.
- Write `@wip` scenarios only for that behaviour. Step 5 tells how. Keep the scenarios of the other sub-issues as they are.
- Create no sub-issue. The sub-issues exist already.
- For each sub-issue, remove the label and name the scenarios drafted for it. Add one `--scenario` per scenario. A sub-issue without a scenario takes no `--scenario`, and then its `Scenarios:` list is removed:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n" --clear "$child" --scenario "<scenario name>"
  ```

  The script removes the label if the sub-issue still carries it. It replaces the list under the `Scenarios:` line in the body with the given names, as code spans, without duplicates. Then it re-reads the sub-issue and checks that the list is exactly those names. A non-zero exit means the edit did not land. Run the same command again: it also accepts an open sub-issue whose label is gone already. If it fails again, stop. Report the failure. A scoped repeat runs the same command, so its `Scenarios:` list names the renamed scenarios.
- For an approved exempt sub-issue, add `--no-red-green` to that command (see **Red-green exemption**).
- Before you ask for the approval, set the stage back to `drafting-spec`, so the new text needs its own approval:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" drafting-spec
  ```

- Then do steps 6 and 7. A scoped draft ends at the approval step. `sdd-flow-tdd` implements the sub-issues after the label is `spec-approved`.

## Red-green exemption

`sdd-flow-tdd` closes a sub-issue only after a failing `test:` commit comes before its `feat:` or `fix:` commit. Some work has no behaviour to test first, for example a hook declaration or a docs-only change. Only this skill can exempt such a sub-issue, and only with the user's approval.

- Record one `## Open decisions` question per exempt sub-issue. Use exactly this wording, with the exact sub-issue title:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "Exempt the sub-issue <title> from the red-green check?"
  ```

- Ask the user the question. Do not continue that sub-issue until the user answers. Never check off the line before the user answers, and never write an answer that the user did not give. The user can check off the line on GitHub, with `→ yes` or `→ no` after the question. Or, when the user answers you, record that answer as the resolution. Start an approval with `yes`, and a rejection with `no`:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check-open-decision.py" "$n" --question "Exempt the sub-issue <title> from the red-green check?" --resolved-as "yes (user, <date>)"
  ```
- On a first draft, create the approved sub-issue with the exemption label:

  ```bash
  child=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-sub-issue.py" "$n" --title "<title>" --no-red-green)
  ```

- In scoped mode, the sub-issue exists already. Add the flag to its clear command:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n" --clear "$child" --no-red-green
  ```

- Both scripts refuse unless a checked `## Open decisions` line asks exactly that question for the sub-issue title. Its resolution must also start with `yes`, `approved` or `exempt`. A line that only mentions the title, a line with no resolution and a rejection are not approvals. A refusal means that the user did not approve the exemption. Report the refusal to the user.
- If the user rejects the exemption, do not use the flag. `sdd-flow-tdd` then needs a failing test first.

## Common Mistakes
- Drafting on the main branch / main checkout instead of the feature's worktree. Step 2 is not optional, even for a single-file spec amendment.
- Writing a new heading per feature instead of amending the existing one for that concept. This is exactly the frozen-per-feature-file pattern this workflow replaces. (A new heading for a genuinely new *concept* in an existing file is fine — see step 3's third case.)
- Leaving out the **Out of scope:** line. Write `none` when the intent leaves nothing out.
- Writing a scenario without the `@wip` tag. The build gate then runs a scenario that fails.
- Leaving an empty **Decisions:** heading with no bullets under it — omit the heading instead.
- Only handling the first path in `**Spec files:**` when an intent spans more than one module.
- Inventing a branch name instead of using the issue body's `**Branch:**` line. The number in `sdd/<n>-<slug>` is how every later skill finds this issue.
- In scoped mode, creating new sub-issues or drafting behaviour that no `sdd:needs-spec` sub-issue names. Draft only the labelled sub-issues. Clear each label.
