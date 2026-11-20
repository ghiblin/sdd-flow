# Release notes

## v0.2.4 (2026-11-20)

- Round 2 of Plan review and Spec review now re-dispatches only the reviewer role(s) that had a blocking finding in round 1, instead of the full tier-scoped panel read fresh from `get-tier-profile` each round. A role that gave round 1 a clean bill is reviewing a diff that is, by construction, a fix for someone else's finding, so it's skipped on the re-review. Roughly halves reviewer subagent calls on a multi-round plan/spec review loop (the common case being 1-2 roles out of 3 flagging something) ([#23](https://github.com/ghiblin/sdd-flow/issues/23)).

## v0.2.3 (2026-11-20)

- `sdd-flow-intent`'s Complexity gate (step 4) now actively scans for a multi-layer/multi-service signal — an intent that names two or more layers or services as separate deliverables (e.g. "backend doesn't exist yet, plus frontend and a fake email service") — and treats it as a **default split**, instead of leaving the split judgment entirely to open-ended "does it decompose?" discretion. Root cause: a 2026-11-19 diet-pal session ran exactly this shape of intent as one monolithic Tier-2 run (~12h15m, 41 subagents, full PM/tech-lead/QA review fan-out applied twice across the whole scope) because the old wording never fired on the common case of explicitly-named separate deliverables ([#21](https://github.com/ghiblin/sdd-flow/issues/21)).

## v0.2.2 (2026-11-20)

- The orchestrator now offers to stop and print the resume command (`claude --agent sdd-flow "#<n>"`) at two more boundaries — after Checkpoint Plan's approval and after Checkpoint A's approval — not only at Checkpoint B. Previously it only ever exited at Checkpoint B or on Failure, so a Plan review loop, a Draft review loop and several Implement sub-issues could all pile into one long-lived session that kept re-paying the cache-read cost of its own growing transcript. Since `claude --agent sdd-flow "#<n>"` already resumes correctly from GitHub + worktree state (used by Checkpoint B and Failure already), this reuses the same resume path, just offered more often ([#22](https://github.com/ghiblin/sdd-flow/issues/22)).

## v0.2.1 (2026-11-18)

- New `sdd-flow-merge-pr` skill (`/sdd-flow:sdd-flow-merge-pr <worktree-name>`) wrapping `merge_pr.py`. Previously the orchestrator's final report told the user that `${CLAUDE_PLUGIN_ROOT}/scripts/merge_pr.py` "handles merge + teardown" — but that variable only resolves when Claude Code loads plugin markdown, never in the user's own shell, so there was no actual way to run it once installed as a plugin.

## v0.2.0 (2026-11-17)

New **Plan** stage and **Plan Review**, inserted between `sdd-flow-intent` and `sdd-flow-draft`, plus a backtrack path from drafting back to intent — a rework of the pipeline's front half based on real-world feedback:

- New `sdd-flow-plan` skill: writes a high-level, issue-only plan (`## Plan` block on the main issue) — approach, components, major flow, trade-offs; explicitly no Gherkin, no code, no file-level task breakdown. New `sdd:stage:planning`/`sdd:stage:plan-approved` labels, inserted before `drafting-spec` in the state machine.
- **Plan review**: the same PM/tech-lead/QA reviewer roles used for spec review now also run against the plan, tier-scoped by a new `plan_review_roles` config key (same defaults as `spec_review_roles`, independently tunable).
- **ADR check** moves from `sdd-flow-draft` to `sdd-flow-plan`, and now runs at every tier unconditionally (previously gated behind a Tier-2-only `adr_check` flag, now removed). The ADR scripts/template (`create-adr.py`, `templates/adr.md`) moved from being local to `sdd-flow-draft` to the plugin's shared `scripts/`/`templates/` directories.
- `sdd-flow-intent`'s elicitation is now an iterative **Challenge loop**: it raises one open question at a time (scope, constraints, edge cases, dependencies, non-goals, "how will we know this is done") and keeps going until a fresh pass finds nothing left to raise, instead of a single best-effort pass. Settled rounds are recorded as pre-resolved `## Open decisions` lines via a new `create-issue.py --resolved-decision` flag.
- `sdd-flow-draft` now seeds Architecture/Decisions from the already-approved plan instead of inventing them from scratch, and defines a concrete **Backtrack** test: a finding that would change the plan, invalidate an ADR, or have changed the tier ends the stage with a new `NEEDS_REPLAN` block (the orchestrator re-dispatches `sdd-flow-intent`) instead of being patched in place.
- "Approval criteria" is now explicit: the spec section's Criteria bullets support a third tag form, `[criteria: …]`, for a manual check, metric threshold, or migration-verification query — not just a BDD scenario or a named test.

## v0.1.3 (2026-11-04)

- Fix `sdd_route.py` and `sdd_check_state.py` running `gh`/their helper scripts in this script's own directory instead of the caller's working directory. As an installed plugin that directory is the marketplace cache (`~/.claude/plugins/cache/...`), not a git repo at all, so every route/state check failed with `fatal: not a git repository`. Both now inherit the caller's cwd, like every other script in `scripts/`.
- Fix the same class of bug in `merge_pr.py`: it resolved the feature's worktree, and ran every `git`/`gh` teardown command, against its own install/cache directory instead of the project's main checkout. It now finds the main checkout via `git rev-parse --git-common-dir`, the same method `sdd-flow-init` already uses, so it works correctly as an installed plugin and from inside a feature worktree.

## v0.1.2 (2026-11-04)

- New `sdd-flow` skill: a thin wrapper that dispatches the orchestrator agent via the Agent tool, so it can be launched as `/sdd-flow "<intent>"` or `/sdd-flow "#<issue>"` from inside an existing session instead of requiring a separate `claude --agent sdd-flow` terminal launch.

## v0.1.1 (2026-11-04)

- `sdd-flow-code-reviewer` now checks a project's optional `constitution.md` Simplicity section (speculative features, unrequested abstractions, reinvented stdlib/existing code), always as a `follow-up:` finding — never `blocking:` — so it can never justify dropping validation, error handling, or a spec-required edge case.

## v0.1.0 (2026-11-02)

Initial release. Ported from a project-local SDD workflow (diet-pal's `sdd-*` skills), generalized into a standalone, installable Claude Code plugin, and redesigned around three weight-class tiers so a mechanical change no longer pays feature-grade review ceremony.

- Three tiers (0 mechanical / 1 bugfix / 2 feature), classified by `scripts/tier_classifier.py` and confirmed by the user, recorded as an `sdd:tier:<n>` label.
- One shared `scripts/`/`templates/` directory (deduplicated from the per-skill copies of the source project).
- `scripts/sdd_flow_config.py`: a project-local `.claude/sdd-flow.local.md` config file, with defaults for every key and an `IMPLEMENTED` registry that fails loudly (naming the tracking issue) on an unimplemented choice instead of silently falling back.
- Red → green → optional refactor: a discretionary refactor step after green, gated by the tier profile's `refactor_step`, rerunning the build gate before it reaches review.
- The hard build-gate check (`sdd_gate_guard.py` + `gate_marker.py`'s tree-hash marker) is kept as-is on real project code, at every tier — it was never the source of the overhead this release fixes.
- Desktop/phone notifications are config-gated (`notifications.desktop`/`push`), off by default — they were a personal environment convenience, not core to the workflow.

Known gaps, tracked as issues (see `docs/config-reference.md`):
- `state_backend: local-file` — not implemented; `github-issues` is the only backend today.
- Deeper orchestrator state-machine tier-awareness (e.g. an explicit Tier-0 skip of Checkpoint A's approval question) is only partially threaded through; the review-fan-out and reviewer-role gating is fully wired, the stage-table shape is intentionally unchanged across tiers.
