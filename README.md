# sdd-flow

A spec-driven-development (SDD) workflow for Claude Code, packaged as an installable plugin, with one core idea: **not every change deserves the same ceremony.**

## Why

A pipeline built for ambiguous, judgment-heavy features — spec draft, multi-role spec review, TDD with code review, independent pre-PR review — is the right amount of process for a feature. It is wildly wrong for a mechanical refactor with no behavior change. Running every change through the same heavy loop means a "split this file" task pays for three parallel spec reviewers, a full red/green TDD cycle, and two independent pre-PR reviewers — ceremony built for judgment calls, spent on something that needed none.

sdd-flow classifies every intent into one of three tiers and scales the pipeline to match.

## Tiers

| Tier | Qualifies when | Spec review | Implementation | Pre-PR review |
|---|---|---|---|---|
| **0 — mechanical** | No behavior change; build gate already green before the change (refactor, file split, rename, dependency bump) | None — one-paragraph description, no spec, no Gherkin | One batch: the whole intent is one unit, one worktree, no per-file sub-issues, no red/green | One code-review pass over the whole diff |
| **1 — bugfix** | Behavior changes, but the root cause is already narrow and known | One reviewer role (tech lead), short spec = description + the regression test | Red → green → optional refactor, typically one sub-issue | One code-review round |
| **2 — feature** | Real ambiguity or a judgment call | PM + tech lead + QA, up to 2 rounds | Red → green → optional refactor per sub-issue, reconcile after each | Independent code-review + spec-conformance fan-out, up to 2 rounds |

Classification happens once per intent (and once per split-off piece, if `sdd-flow-intent` splits a batch into independent pieces), proposed by a small heuristic (`scripts/tier_classifier.py`) and always confirmable or overridable by you — see `tiers.classification` below.

## What's kept from a traditional heavyweight SDD setup, and why

- **GitHub issue as a resumable state machine.** A long-running, multi-session feature needs to survive a session dying mid-way. Stage labels (`sdd:stage:*`) and a tier label (`sdd:tier:*`) on the main issue carry that state.
- **Worktree-per-feature.** Keeps `main` clean regardless of tier; cheap enough to apply everywhere.
- **The hard build-gate check before closing work.** `close-sub-issue.py` and the `sdd_gate_guard.py` hook refuse to close a sub-issue or mark a stage complete/verified without a fresh, clean-tree, passing build-gate run — on real project code, every tier. This is not the thing that was overcomplicated; the ceremony *around* deciding whether a change needed a 3-reviewer spec debate was.
- **The planner/reviewer separation.** An implementer never judges its own code; a spec writer never judges its own spec. Kept at every tier — just with fewer roles at the lighter tiers.
- **Red → green → optional refactor.** The classic third TDD step, discretionary and gated by a rerun of the build gate so a refactor that breaks something is caught before review, not after.

## What's new here vs. a non-tiered setup

- The tier classifier and the `sdd:tier:*` label.
- A single config file (below) instead of hardcoded ceremony.
- One shared `scripts/` and `templates/` directory instead of per-skill duplicates.
- No gate-marker machinery applied to *this plugin's own development* — see `docs/config-reference.md` if you're extending sdd-flow itself.

## Installing

Add this plugin to a project, then run its `sdd-flow-init` skill once to create the GitHub labels (`sdd:*`) and record the project's source directories. Launch the orchestrator as the main session:

```
claude --agent sdd-flow "<a one- or two-sentence intent>"
claude --agent sdd-flow "#<issue-number>"   # resume
```

## Configuring

See `docs/config-reference.md` for the full key reference, including which alternatives are tracked-but-not-built yet (and fail loudly with their tracking issue if you select them, rather than silently falling back).

## Repo layout

```
.claude-plugin/plugin.json   plugin manifest
agents/                      the orchestrator + its subagents (sdd-flow-*)
skills/                      the 6 pipeline skills (sdd-flow-init/intent/draft/tdd/reconcile/pr-validate)
hooks/                       sdd_gate_guard.py (hard build-gate check) + sdd_feature_guard.py (implementer can't edit feature files)
scripts/                     shared stdlib-Python helpers + their unittest suites
templates/                   shared issue-body templates
docs/config-reference.md     every config key, default, and tracking issue for unimplemented ones
```
