---
name: sdd-flow-intent
description: Use when starting work on a new feature or change under the SDD workflow, before drafting any spec or writing code.
---

# Spec-Anchored Intent

**Helper paths:** `<base>` stands for this skill's base directory — the path on the `Base directory for this skill:` line the skill loader prints above this text. Substitute it literally wherever a command or path below names `<base>/scripts/…` or `<base>/templates/…`; never rewrite it as a repo-relative path, so the same text works from the repo copy and from the global `~/.claude/skills` copy.

## Overview
Turns a one- or two-sentence intent into: a DDD context (does this entity/module exist, what's its current shape), a target spec file, a complexity decision, a **tier** (how much of the pipeline's ceremony this intent actually needs), and a **GitHub main issue** to resume from later.

## Steps

1. **State intent.** One or two sentences (e.g. "add a router pattern to the agent loop"). Reject vaguer input — ask the user to sharpen it first.
   - **Elicit, don't assume, when something the spec would later need is genuinely missing.** Once the intent clears the rejection check above, scan it against three dimensions: a scope boundary (what this explicitly does *not* cover), a constraint or non-functional requirement the wording implies but never states (performance, compatibility, security), and an edge case the one/two sentences gloss over. Ask about a dimension only when it is genuinely open **and** guessing wrong would change the spec's shape later — this is not a mandatory checklist run on every intent, and a Tier-0-shaped mechanical ask (a rename, a file split, a dependency bump) already answers all three by having no behavior to bound.
   - If any dimension is open, ask one `NEEDS_INPUT` covering every open dimension together — never one round-trip per dimension. The issue doesn't exist yet, so there is nowhere to record the answer until step 6; fold it into the sharpened intent text you carry into steps 2-6.
   - Don't re-ask a dimension that steps 2-5 settle on their own — e.g. the DDD check in step 2 can answer a scope-boundary question just by showing the module doesn't exist yet.
2. **DDD check.** Query the graphify graph for the entity/module named or implied by the intent: `graphify query "<intent>"` and/or `graphify explain "<ModuleName>"`. Determine: does it already exist, what's its current bounded context, what does it currently expose (callers/callees, public API). Do not open source files to answer this: the graph query is the answer. Read a file only if the graph has no match at all.
3. **Resolve target spec file(s).** One file per module/bounded-context lives at `docs/specs/<module-slug>.md`. If the project groups specs into topic folders, it lives at `docs/specs/<topic>/<module-slug>.md` instead. Pick `<topic>` by the project's documented folder rule (a feature spanning two topics gets one file in each). Reuse the existing file if the module already has one; otherwise this intent creates it. An intent may touch more than one module — list all of them.
4. **Complexity gate.** If the intent decomposes into independent pieces (each buildable and testable on its own), stop here. Hand off with this **REQUIRED SUB-SKILL:** use `superpowers:using-git-worktrees` to create one worktree per piece. Then use `superpowers:subagent-driven-development` or `superpowers:dispatching-parallel-agents` to run each piece through this same workflow independently. Otherwise continue as a single task. Each independent piece gets its **own** `sdd-flow-intent` run and its own main issue — pieces are never sub-issues of a shared epic. (Sub-issues are development increments under one worktree, created later by `sdd-flow-tdd`.) Classify each piece's tier (step 5) separately — a split intent is never a single tier for the whole batch.
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
     --decision "<significant question the intent already raises>" \
     --tier <the tier confirmed in step 5>)
   ```

   Repeat `--spec-file` once per path from step 3. Repeat `--decision` once per question. With no questions, omit `--decision`; the block then reads `- [ ] _none_`. The script renders `<base>/templates/main-issue.md`, the `<!-- sdd:begin -->`…`<!-- sdd:end -->` block. No line of it has leading whitespace, because later skills match its lines anchored at `^`. The script creates the issue with `sdd:feature`, `sdd:stage:drafting-spec` and `sdd:tier:<n>`. It rewrites the body once with `**Branch:** sdd/<number>-<slug>`. Then it re-reads the issue. A non-zero exit means the body or labels did not land. Stop. Do not retry blindly. Report the failure. Its tests run with `python3 -m unittest discover -s "<base>/scripts"`.

   The branch `sdd/<issue-number>-<slug>` is created later by `sdd-flow-draft` via `superpowers:using-git-worktrees`; it is only *named* here. Do not create the worktree in this skill.

## Common Mistakes
- Running step 1's elicitation as a fixed checklist on every intent, even an obviously mechanical one — this re-adds exactly the ceremony tax tier classification exists to avoid.
- Asking a vague "can you give more detail?" instead of naming the specific dimension (scope boundary, constraint, edge case) that is actually open.
- Skipping the graphify query and grepping/opening files instead — defeats the entire point of the index.
- Creating a new spec file when an existing module file already covers this area. Always check `docs/specs/` first (and every topic folder, if the project has them).
- Creating the worktree/branch in this skill — `sdd-flow-intent` only *names* the branch (`sdd/<number>-<slug>`); `sdd-flow-draft` creates it.
- Classifying a batch of several mechanical pieces (e.g. "split these 7 files") as one Tier 2-sized epic, or skipping tier classification entirely and letting the rest of the pipeline assume Tier 2 by default — this is the mistake that turned diet-pal issue #491 into 7+ feature-grade review cycles for a zero-behavior-change refactor.
- Guessing `--build-gate-green-before` instead of actually running the project's build gate before classifying.
