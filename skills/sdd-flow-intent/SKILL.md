---
name: sdd-flow-intent
description: Use when starting work on a new feature or change under the SDD workflow, before drafting any spec or writing code.
---

# Spec-Anchored Intent

**Helper paths:** `<base>` stands for this skill's base directory — the path on the `Base directory for this skill:` line the skill loader prints above this text. Substitute it literally wherever a command or path below names `<base>/scripts/…` or `<base>/templates/…`; never rewrite it as a repo-relative path, so the same text works from the repo copy and from the global `~/.claude/skills` copy.

## Overview
Turns a one- or two-sentence intent into: a DDD context (does this entity/module exist, what's its current shape), a target spec file, a complexity decision, a **tier** (how much of the pipeline's ceremony this intent actually needs), and a **GitHub main issue** to resume from later. The intent's open questions are settled *here*, before `sdd-flow-plan` writes anything — see **Challenge loop** below.

## Steps

0. **Replan re-entry.** If your stage note starts with "Replan:", this is not a new intent — `sdd-flow-draft` backtracked here because a solution-impacting discovery means the plan needs to change. Do this instead of step 1 onward:
   - Resolve `n` from the note (it names the issue), not from the branch — you may be invoked before any worktree exists for this session.
   - Read the existing issue: `gh issue view "$n" --json number,title,body,labels`.
   - Move the stage back to `planning` first, so the state machine reflects that the plan is being revised: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" planning`.
   - Run the Challenge loop (step 1 below), seeded with the discovery as the first thing to settle — treat it exactly like an open dimension the original intent missed. Unlike a first-time intent, the issue already exists: append each settled round live with `add-open-decision.py`/`check-open-decision.py` (open, then checked), rather than carrying them to a `create-issue.py` call that will never happen in this branch.
   - Re-run tier classification (step 5) only if the discovery itself could plausibly change the tier. Skip the DDD check (step 2), spec-file resolution (step 3) and the complexity/split gate (step 4) unless the discovery bears on them — most replans don't.
   - Do not call `create-issue.py`. Report `DONE` exactly as a normal Stage-1 dispatch would (the stage label is now `planning`, so the orchestrator's **Stages** table sends this straight to a fresh `sdd-flow-plan` dispatch).
1. **State intent and run the Challenge loop.** One or two sentences (e.g. "add a router pattern to the agent loop"). Reject vaguer input — ask the user to sharpen it first.
   - **Challenge, don't assume, when something the plan would later need is genuinely missing.** Once the intent clears the rejection check above, scan it against every dimension that could change the plan's shape: a scope boundary (what this explicitly does *not* cover), a constraint or non-functional requirement the wording implies but never states (performance, compatibility, security), an edge case the one/two sentences gloss over, a dependency on another module or team, a non-goal worth stating explicitly, and "how will we know this is done" (the shape approval criteria will eventually take). This is not a mandatory checklist run on every intent — a Tier-0-shaped mechanical ask (a rename, a file split, a dependency bump) already answers all of these by having no behavior to bound, and short-circuits straight past this loop.
   - **Raise one open point per round, never batched.** Ask a single `NEEDS_INPUT` for the single most load-bearing open dimension — the recommended option first. Record the round in order as `(question, answer)`; the issue doesn't exist yet, so these rounds accumulate in your own turn, carried into step 6's `--resolved-decision` flags, not written anywhere until then.
   - **Keep going until nothing is left to raise.** After each answer, re-scan the now-sharper intent (plus whatever DDD context step 2 has already surfaced) for the next open dimension. Stop only when a fresh pass finds nothing left to challenge — not after a fixed number of rounds. Don't re-ask a dimension that steps 2-5 settle on their own — e.g. the DDD check in step 2 can answer a scope-boundary question just by showing the module doesn't exist yet.
   - **This is a challenge, not a survey.** Push back on an answer that is itself vague or that reopens a question a prior round already settled, the same way step 1's rejection check pushes back on a vague intent. Don't accept "whatever you think is best" as a settled answer to a dimension that genuinely changes the plan's shape — ask the user to choose, with your recommendation first.
2. **DDD check.** Query the graphify graph for the entity/module named or implied by the intent: `graphify query "<intent>"` and/or `graphify explain "<ModuleName>"`. Determine: does it already exist, what's its current bounded context, what does it currently expose (callers/callees, public API). Do not open source files to answer this: the graph query is the answer. Read a file only if the graph has no match at all.
3. **Resolve target spec file(s).** One file per module/bounded-context lives at `docs/specs/<module-slug>.md`. If the project groups specs into topic folders, it lives at `docs/specs/<topic>/<module-slug>.md` instead. Pick `<topic>` by the project's documented folder rule (a feature spanning two topics gets one file in each). Reuse the existing file if the module already has one; otherwise this intent creates it. An intent may touch more than one module — list all of them.
4. **Complexity gate.** Don't just wait for decomposition to be "independently obvious" — actively scan the intent for a concrete split signal first:
   - **Multi-layer/multi-service signal (default split).** The intent names two or more layers or services as separate deliverables — e.g. a backend plus a frontend, plus a separate fake/mock service; a migration plus the code that depends on it; a library plus its consumers. Wording like "backend doesn't exist yet, plus frontend and a fake email service" is the textbook shape — each named layer/service is its own piece by default. Treat this as a **default split**: split unless there's a concrete reason the named pieces can't be built or tested apart (genuinely inseparable coupling), not merely because splitting wasn't independently obvious.
   - **General decomposition.** Beyond that pattern, if the intent decomposes into independent pieces (each buildable and testable on its own) for any other reason, split as well.

   If either check finds a split, stop here. Hand off with this **REQUIRED SUB-SKILL:** use `superpowers:using-git-worktrees` to create one worktree per piece. Then use `superpowers:subagent-driven-development` or `superpowers:dispatching-parallel-agents` to run each piece through this same workflow independently. Otherwise continue as a single task. Each independent piece gets its **own** `sdd-flow-intent` run and its own main issue — pieces are never sub-issues of a shared epic. (Sub-issues are development increments under one worktree, created later by `sdd-flow-tdd`.) Classify each piece's tier (step 5) separately — a split intent is never a single tier for the whole batch, and a lower-tier piece (e.g. a frontend form or a fake service) must not inherit the most complex piece's tier.
5. **Tier classification.** This is the step that decides how much ceremony the rest of the pipeline pays — see the plugin's tier table (0 mechanical / 1 bugfix / 2 feature) in the top-level README. Get the pre-change build-gate state first (`true` only if the project's own build gate, run now, passes on a clean tree — a dirty or failing gate before any change starts rules out Tier 0's "no behavior change" claim): then run

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tier_classifier.py" "<the one/two sentence intent>" --build-gate-green-before=true|false
   ```

   It prints `tier: <0|1|2>`, a one-line rationale, and a ready-made question. Read `tiers.classification` from `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sdd_flow_config.py" . get tiers.classification` (defaults to `auto`).
   - `always-ask`: always surface the printed question as a `NEEDS_INPUT` (the proposed tier first, marked recommended). Apply whichever tier the user confirms or picks.
   - `auto`: surface the `NEEDS_INPUT` only when the classifier's own reasoning names an open judgment call (its rationale mentions ambiguity, a design question, or a claimed behavior change alongside mechanical wording) — otherwise take the proposed tier without asking, and say so in one line when you report back ("classified as Tier `<n>` — `<rationale>`; this one wasn't ambiguous enough to ask about").
   Record the confirmed tier; step 6 passes it to `create-issue.py --tier`.
6. **Create the main issue.** Choose `<feature-slug>` as a short kebab-case name for the intent.

   **Preconditions:** `gh auth status` green and a GitHub `origin`. If the first `gh` call fails on auth, stop. Tell the user to run `gh auth login`.

   Run the helper from the repo root; it prints the new issue's number:

   ```bash
   number=$(python3 "<base>/scripts/create-issue.py" \
     --slug "<feature-slug>" --intent "<the one/two sentence intent>" \
     --spec-file <spec-file path from step 3> \
     --resolved-decision "<question from a Challenge loop round> -> <the user's answer>" \
     --decision "<a dimension step 1 raised but left open, if any>" \
     --tier <the tier confirmed in step 5>)
   ```

   Repeat `--spec-file` once per path from step 3. Repeat `--resolved-decision` once per settled Challenge-loop round, in the order they were settled — use `->` on the command line (the script renders the real `→`). Repeat `--decision` only for a dimension the Challenge loop could not settle (rare — the loop is supposed to run until nothing is left). With neither, the block then reads `- [ ] _none_`. The script renders `<base>/templates/main-issue.md`, the `<!-- sdd:begin -->`…`<!-- sdd:end -->` block, including an empty `## Plan` placeholder that `sdd-flow-plan` fills in next. No line of it has leading whitespace, because later skills match its lines anchored at `^`. The script creates the issue with `sdd:feature`, `sdd:stage:planning` and `sdd:tier:<n>`. It rewrites the body once with `**Branch:** sdd/<number>-<slug>`. Then it re-reads the issue. A non-zero exit means the body or labels did not land. Stop. Do not retry blindly. Report the failure. Its tests run with `python3 -m unittest discover -s "<base>/scripts"`.

   The branch `sdd/<issue-number>-<slug>` is created later by `sdd-flow-plan` via `superpowers:using-git-worktrees`; it is only *named* here. Do not create the worktree in this skill.

## Common Mistakes
- Running step 1's Challenge loop as a fixed checklist on every intent, even an obviously mechanical one — this re-adds exactly the ceremony tax tier classification exists to avoid.
- Stopping the Challenge loop after one round, or batching every open dimension into a single question, instead of raising one at a time and continuing until a fresh pass finds nothing left.
- Asking a vague "can you give more detail?" instead of naming the specific dimension (scope boundary, constraint, edge case, dependency, non-goal, done-definition) that is actually open.
- Accepting a vague or deflecting answer as settled instead of pushing back once, the way the intent-sharpening rejection check already does.
- Skipping the graphify query and grepping/opening files instead — defeats the entire point of the index.
- Creating a new spec file when an existing module file already covers this area. Always check `docs/specs/` first (and every topic folder, if the project has them).
- Creating the worktree/branch in this skill — `sdd-flow-intent` only *names* the branch (`sdd/<number>-<slug>`); `sdd-flow-plan` creates it.
- Classifying a batch of several mechanical pieces (e.g. "split these 7 files") as one Tier 2-sized epic, or skipping tier classification entirely and letting the rest of the pipeline assume Tier 2 by default — this is the mistake that turned diet-pal issue #491 into 7+ feature-grade review cycles for a zero-behavior-change refactor.
- Treating an intent that names multiple layers/services as separate deliverables (e.g. "backend doesn't exist yet, plus frontend and a fake email service") as one monolithic task because the split wasn't "independently obvious" — this is the mistake that turned a passwordless-auth intent into a single ~12h, 41-subagent Tier-2 run with full PM/tech-lead/QA review fan-out applied to pieces that didn't need it (issue #21). Look for the multi-layer/multi-service naming pattern as a default-split signal first, rather than relying only on open-ended decomposition judgment.
- Guessing `--build-gate-green-before` instead of actually running the project's build gate before classifying.
- On a Replan re-entry (step 0), calling `create-issue.py` or skipping the `set-stage.py … planning` call — the issue already exists; this run amends it, it does not create a second one.
