---
name: sdd-flow-plan
description: Use when the sdd-flow-intent step has created the main issue and it's time to write or amend the high-level plan for that intent, before any spec text, scenarios or code exist.
---

# Spec-Anchored Plan

**Helper paths:** most scripts this skill uses are shared across the sdd-flow plugin, at `${CLAUDE_PLUGIN_ROOT}/scripts/…`. This skill's own `set-plan.py` lives at `<base>/scripts/set-plan.py`, where `<base>` is this skill's own base directory (the path on the `Base directory for this skill:` line the skill loader prints above this text) — it is specific to this skill because no other skill rewrites the issue body's `## Plan` block.

## Overview

Writes a short, high-level plan into the main issue's `## Plan` block: the approach, which components/modules it touches, the major flow, and the key trade-offs. Explicitly **no** Gherkin scenarios, no code, and no file-level task breakdown — that detail belongs to `sdd-flow-draft` and `sdd-flow-tdd`, after the plan itself is approved. The plan lives only on the issue (it is not written into `docs/specs/`); approving it is cheap to redo and cheap to discard, which is the point — it is meant to be challenged and revised before any spec or test exists to make revising expensive.

Any decision in the plan that picks between viable approaches, is expensive to reverse, or crosses a module boundary gets an ADR — see **ADR check** below. This is the pipeline's primary ADR trigger point, and it runs at every tier.

## Tier profile

Before step 1, read the main issue's `sdd:tier:<n>` label and load its profile: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_flow_config.py" . get-tier-profile <n>`.

- **Tier 0** (`plan_review_roles: []`): write one short line into the `## Plan` block — what the batch changes and why it's behavior-preserving. No Plan review loop. The ADR check still runs, but a genuinely mechanical Tier-0 batch has no architecture decision to flag in practice.
- **Tier 1** (`plan_review_roles: [tech-lead]`): a short plan — the approach and its main trade-off is usually enough for a bugfix-sized change. Plan review runs with only the tech-lead role.
- **Tier 2** (`plan_review_roles: [pm, tech-lead, qa]`): the full plan — approach, components touched, major flow, trade-offs. All three roles review, up to two rounds.

## Steps

0. **Resolve the main issue.** `n=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-issue.py")`. If it exits non-zero, stop: the session is not on an `sdd/<n>-<slug>` branch. Tell the user to run `sdd-flow-intent` or to check out the feature branch. Read the issue with `gh issue view "$n" --json number,title,body,labels`. Check the stage note first:
   - If the stage note starts with "Approval resume", the user approved this plan. Skip straight to the approval commands at the end of step 6. Do nothing else.
   - If the stage note contains "The user requested these changes to the plan", this is a "Request changes" repeat. Before you write anything, check off the open approval line with the highest `k` as `changes requested` (see step 6). Then go on below, revising the plan content with the requested change.
1. From the issue body block (between `<!-- sdd:begin -->` / `<!-- sdd:end -->`), read `**Intent:**`, `**Worktree:**` and `**Branch:**`.
2. **Always write the plan in the feature's worktree — never on the main branch or the main checkout.** The issue body's `**Worktree:**` line is the repo-relative worktree path that `sdd-flow-intent` recorded; its `**Branch:**` line is the exact branch name (`sdd/<n>-<slug>`). **REQUIRED SUB-SKILL:** use `superpowers:using-git-worktrees` to ensure that worktree exists on that branch. If it is absent, create it from the current main branch. Do the rest of this skill from inside it. If this session is already confined to that worktree, just confirm the path matches. The worktree matters here only because **ADR check** below writes a tracked file (`docs/adr/`) that must land on the feature branch — the plan text itself is an issue-body edit, not a file in the checkout.
3. **Write the plan.** Compose the plan content per the tier profile above. Write it to a scratch file, then:

   ```bash
   python3 "<base>/scripts/set-plan.py" "$n" --body-file <scratch file>
   ```

   It replaces the `## Plan` block's content (everything between the `## Plan` heading and the next `#`/`##`-level heading or `<!-- sdd:end -->` — an internal `###`+ subheading inside your own plan content does not end the block early, so structure a Tier 2 plan with subheadings freely). It refuses unless the body has exactly one `## Plan` heading, re-reads the issue afterward, and exits non-zero if the block does not match what was written. A non-zero exit means stop. Do not retry blindly. Report the failure.
4. **ADR check** (see below) — run it against the plan content you just composed, before step 3's write if you want the ADR reference inlined, or as a follow-up edit to the same block otherwise. Either order is fine as long as every ADR-worthy decision in the written plan carries its `(see docs/adr/ADR-NNN-<slug>.md)` reference.
5. Once the plan is written and every ADR check question is settled, end your turn with a `NEEDS_PLAN_REVIEW` block. Use the format your dispatch prompt gives. The results come back in a message starting `PLAN REVIEW RESULTS:`. Each finding is tagged `blocking:` or `follow-up:`. Fix each blocking finding (amend the plan with `set-plan.py` again) before continuing. File each follow-up finding as an issue with `create-follow-up.py`. Ask for round 2 only if round 1 had a blocking finding; never ask for round 3. After round 2, record each blocking finding that is still open as an `## Open decisions` question and ask the user with one `NEEDS_INPUT` per finding. Do not ask for the approval while a blocking finding is open.
6. **Get the approval.** Add the approval line to `## Open decisions`. Take `k` one above the highest `k` present in lines of the form `Approve the plan? (plan <k>)`, and 1 for a first plan:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "Approve the plan? (plan <k>)"
   ```

   Ask the user exactly that question. Under the `sdd` orchestrator, end your turn with a `NEEDS_INPUT` for it, as your dispatch prompt describes. The orchestrator shows the user the `## Plan` block and any new `docs/adr/*.md` files before it relays the question. A "Request changes" answer repeats from step 0's second case. After the user approves, check the line off and set the stage:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check-open-decision.py" "$n" --question "Approve the plan? (plan <k>)" --resolved-as "approved"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" plan-approved
   ```

   The script refuses unless the highest-numbered approval line is checked `yes` or `approved`. Never check it off before the user answers, and never write an approval the user did not give. It re-reads the issue afterward; a non-zero exit means the approval, the label or the body did not land. Stop. Do not retry blindly. Report the failure.

## ADR check

Runs at **every tier**, unconditionally — not gated by any tier-profile flag. For each decision the plan states, ask: does it pick between two or more viable approaches, is it expensive to reverse, or does it affect more than this module? A narrow implementation detail ("retry three times") is not ADR-worthy; "use a router instead of a DAG for dispatch" is. Check each decision once, as you compose it — do not batch every decision in the plan into one pass at the end.

- For a flagged decision, add an `## Open decisions` question before writing it into the plan:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "Record '<decision text>' as an ADR?"
  ```

  One question per flagged decision — never one question covering several decisions at once.
- Ask the user exactly that question. Do not write the decision into the plan, and do not create the ADR, before the user answers. Under the `sdd` orchestrator, end your turn with a `NEEDS_INPUT` for it.
- On yes, check the line off and create the ADR, in that order:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check-open-decision.py" "$n" --question "Record '<decision text>' as an ADR?" --resolved-as "yes (user, <date>)"
  path=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-adr.py" \
      --title "<short decision title>" --context "<why this came up>" \
      --decision "<decision text>" --consequences "<what this rules in or out>")
  ```

  `create-adr.py` numbers the file from what is already in `docs/adr/`, writes `docs/adr/ADR-NNN-<slug>.md`, and appends a row to `docs/adr/README.md`. It never shells out to any other command. A non-zero exit means the ADR or its README row did not land. Stop. Do not retry blindly. Report the failure.
- Write the plan's mention of the decision with a trailing reference to the path `create-adr.py` printed: `<decision text> (see docs/adr/ADR-NNN-<slug>.md)`.
- Commit the new ADR file and README row on the feature branch: `git add docs/adr && git commit -m "docs: record ADR-NNN-<slug> (#<n>)"`. This is the only git commit this skill makes — the plan text itself is an issue-body edit via `set-plan.py`, not a tracked file.
- On no, check the line off with `--resolved-as "no (user, <date>)"`, and write the decision into the plan with no ADR reference.
- Never run `create-adr.py` without an explicit yes on the matching open-decision line.

## Common Mistakes

- Writing Gherkin scenarios, a file-level task breakdown, or implementation-level code into the `## Plan` block. That is `sdd-flow-draft`'s and `sdd-flow-tdd`'s job, after this plan is approved.
- Writing the plan into `docs/specs/` instead of the issue's `## Plan` block. The plan is deliberately cheap to discard; a spec file is not.
- Skipping the ADR check because the tier profile looks Tier-0/1-shaped. The check runs at every tier; it simply has nothing to flag on a genuinely mechanical change.
- Batching every ADR-worthy decision in the plan into one question at the end instead of asking once per decision as it comes up.
- Writing or amending `## Plan` by hand with `perl`/`sed` instead of `set-plan.py`. A hand edit can silently corrupt non-ASCII characters elsewhere in the body, and skips the exactly-one-heading precondition and the re-read verification.
- Running the build gate here. Nothing executable changed except, possibly, a new ADR markdown file — there is no code or test for a build gate to check yet.
