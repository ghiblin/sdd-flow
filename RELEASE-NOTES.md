# Release notes

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
