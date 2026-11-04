# Release notes

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
