# Config reference

sdd-flow reads `.claude/sdd-flow.local.md` in the consuming project: YAML-ish frontmatter between two `---` lines, loaded by `scripts/sdd_flow_config.py`. The file is optional — every key has a default, so the plugin works with none of this present. Add it to the project's `.gitignore` (`.claude/*.local.md`), per the Claude Code plugin convention: it's a per-developer/per-project setting, not something to commit.

```yaml
---
state_backend: github-issues
tiers:
  classification: auto
  profiles:
    0: { spec_review_roles: [], code_review_rounds: 1, gherkin_required: false, batch_mode: true, refactor_step: false }
    1: { spec_review_roles: [tech-lead], code_review_rounds: 1, gherkin_required: false, batch_mode: false, refactor_step: true }
    2: { spec_review_roles: [pm, tech-lead, qa], code_review_rounds: 2, gherkin_required: true, batch_mode: false, refactor_step: true }
notifications:
  desktop: false
  push: false
worktree:
  enabled: true
rules_file_glob: "*/RULES.md"
---
```

## Keys

| Key | Default | Meaning |
|---|---|---|
| `state_backend` | `github-issues` | The resumable state machine backend. **Only implemented value.** `local-file` is tracked — see [Unimplemented choices](#unimplemented-choices) below. |
| `tiers.classification` | `auto` | `auto`: `sdd-flow-intent` skips the confirmation question when its classifier is confident (no ambiguity signal in its rationale) and just records the tier. `always-ask`: always ask, even when confident. |
| `tiers.profiles.<0\|1\|2>.spec_review_roles` | see table above | Which of `pm`/`tech-lead`/`qa` run in the Spec review loop. An empty list means no spec review at all (Tier 0). |
| `tiers.profiles.<0\|1\|2>.code_review_rounds` | see table above | Max review rounds before an unresolved finding becomes a user decision instead of another round. |
| `tiers.profiles.<0\|1\|2>.gherkin_required` | see table above | Whether `sdd-flow-draft` must write `@wip` BDD scenarios for this tier. |
| `tiers.profiles.<0\|1\|2>.batch_mode` | see table above | `true` (Tier 0 only by default): the whole intent is one unit — no per-file sub-issues, no red/green cycle. |
| `tiers.profiles.<0\|1\|2>.refactor_step` | see table above | Whether the implementer may make a discretionary refactor commit after green (Tiers 1/2; meaningless at Tier 0, which has no red/green to refactor after). |
| `notifications.desktop` | `false` | Run an `osascript` desktop notification on every `Notify` event. Off by default — this is an environment convenience (started life as one user's macOS/VS Code workaround for Claude Code's own notifications not reaching the desktop), not core to the workflow. |
| `notifications.push` | `false` | Call `PushNotification` on every `Notify` event (reaches a phone only while Remote Control is connected). |
| `worktree.enabled` | `true` | Whether each feature gets its own `.claude/worktrees/<slug>` worktree. There is no implemented alternative yet — see below. |
| `rules_file_glob` | `*/RULES.md` | The glob the reviewer agents use to find per-module rules files (generalized from the single-project convention of one `RULES.md` per crate/module). |

You can override one tier field without repeating the whole profile — the override merges over that tier's default:

```yaml
---
tiers:
  profiles:
    1: { code_review_rounds: 2 }
---
```

## Unimplemented choices

A value listed here is a real, named alternative — tracked as an issue, not a hypothetical. Selecting it raises a `ConfigError` naming the tracking issue, rather than silently falling back to the default.

| Key | Unimplemented value | Tracking issue |
|---|---|---|
| `state_backend` | `local-file` | [sdd-flow#1](https://github.com/ghiblin/sdd-flow/issues/1) — a local-file state machine for projects with no GitHub remote, or for Tier 0/1 work that doesn't want a GitHub issue at all. |

Related, not yet config-gated because it's about the orchestrator's own internal routing rather than a chosen strategy: [sdd-flow#2](https://github.com/ghiblin/sdd-flow/issues/2) — threading tier-awareness all the way through the orchestrator's state machine (Checkpoint A, the Resume table, `sdd_route.py`/`sdd_check_state.py`'s own routing logic), beyond the reviewer-role and round-cap gating v0.1.0 already does.

## Adding a new unimplemented-but-tracked choice

When you want to document a planned alternative without building it yet: add it to `IMPLEMENTED` in `scripts/sdd_flow_config.py` with the tracking-issue URL as its value (not `None` — `None` means "implemented, pick me"), file the issue, and add a row to the table above. `load()` will then reject that value with the issue link instead of ever silently no-op'ing it.
