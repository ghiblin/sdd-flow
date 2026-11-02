---
name: sdd-flow-init
description: Use when adopting the SDD workflow in a repository for the first time, before any feature work begins under it.
---

# Spec-Anchored Init

**Helper paths:** `<base>` stands for this skill's base directory — the path on the `Base directory for this skill:` line the skill loader prints above this text. Substitute it literally wherever a command or path below names `<base>/scripts/…` or `<base>/templates/…`; never rewrite it as a repo-relative path, so the same text works from the repo copy and from the global `~/.claude/skills` copy.

## Overview
One-time per-repository setup for the SDD workflow: the GitHub issue label set that feature state is tracked with, a living-spec directory, and a graphify index scoped to source code only (so it stays free of LLM calls).

## Steps

1. Resolve `<repo-root>` via `git rev-parse --git-common-dir` (parent of that path) — always the main repo root, never the worktree cwd.
2. Create the SDD label set with the script (idempotent — every label goes through `gh label create --force`, so re-running this skill is safe):

   ```bash
   python3 "<base>/scripts/create-labels.py"
   ```

   It creates `sdd:feature`, `sdd:task`, `sdd:needs-spec`, `sdd:no-red-green`, `sdd:follow-up` and the five `sdd:stage:*` labels (`drafting-spec`, `spec-approved`, `implementing`, `complete`, `verified`). It prints one `created <name>` or `present <name>` line per label. Then it re-reads the label list. A non-zero exit means a label is missing or mismatched. Stop. Do not retry blindly. Report the failure. Its tests run with `python3 -m unittest discover -s "<base>/scripts"`.

   The script requires a green `gh auth status` and a GitHub `origin`. If the script fails on auth, stop. Tell the user to run `gh auth login`.
3. If `<repo-root>/docs/specs/` doesn't exist, create it. Living spec files go here, one per module/bounded-context, named `<module-slug>.md`. Once there are more than a handful, group them into topic folders (`docs/specs/<topic>/<module-slug>.md`).
4. Identify the source-code directories to index, such as `src/` or one directory per package/module. Ask the user if the project layout does not make them obvious. Record them at `<repo-root>/.claude/sdd-source-dirs.json` as a JSON array of paths relative to `<repo-root>` (e.g. `["src"]`, or `["core/src", "agent/src", "storage/src"]` for a multi-package repository). Never hardcode a specific project's actual package names. Derive the list from whatever this repository's layout actually is.
5. Build the graph with the raw CLI, never the interactive `/graphify` pipeline, so prose docs never enter the corpus. For each directory `<dir>` in the list, run `graphify extract <dir>` from `<repo-root>`. This writes `<dir>/graphify-out/graph.json`, nested under `<dir>`: that is `graphify extract`'s documented behavior for any non-`.` path. Then unify at the repo root:
   - **More than one directory:** `graphify merge-graphs <dir1>/graphify-out/graph.json <dir2>/graphify-out/graph.json ... --out graphify-out/graph.json` — the documented pattern for monorepo/multi-service layouts (graphify's `references/github-and-merge.md`).
   - **Exactly one directory:** don't call `merge-graphs` at all — it requires at least two inputs. Just relocate it: `rm -rf ./graphify-out && cp -r <dir>/graphify-out ./graphify-out`. Copy, not move: the next reconcile pass re-extracts into the per-directory copy and re-copies from it. The `rm -rf` before the copy is required, not defensive boilerplate. `cp -r` into an already-existing `./graphify-out` nests the source inside it (`./graphify-out/graphify-out/...`) instead of replacing it. That silently leaves the top-level `graph.json` frozen at whatever it was on the previous run. This was verified empirically after two reconcile passes with real code changes. A stale top-level graph still reported the file's very first commit. `graphify explain` (which reads only `<cwd>/graphify-out/graph.json`) kept answering from that frozen copy.
   Either way, this guarantees `<repo-root>/graphify-out/graph.json` exists regardless of source-directory count — every later SDD skill assumes that exact path.
6. Do **not** run `graphify hook install`. It's built around the single-root interactive pipeline, and its incremental-update bookkeeping is unverified against a graph built by manual `extract` + `merge-graphs`. Freshness is instead sdd-flow-reconcile's job — it re-runs step 5's extract-and-merge sequence on every pass.
7. Wire CLAUDE.md: `graphify claude install`. **Then immediately append this override note right after the section it just wrote.** Append only: do not edit or remove graphify's own generated lines. Their exact wording isn't a contract this skill should depend on:

   ```markdown
   **Override for this repo's graphify index:** this graph was built via `graphify extract` + `merge-graphs`/`cp` (sdd-flow-init), not the standard `/graphify` pipeline. Do **not** run `graphify update .` or `graphify --update` here — the copied/merged `graphify-out/`'s manifest paths are relative to the per-directory scan roots, not the repo root, so an update scanning `.` computes different node-ID prefixes for the same files and creates duplicate ghost nodes instead of matching the cache. To refresh the graph, use the sdd-flow-reconcile skill instead — it reruns the correct per-directory extract, then re-merges/re-copies.
   ```

   The note matters because `graphify claude install` writes text that recommends `graphify update .` after code changes. That command corrupts a graph built this way (see graphify's `references/hooks.md`). A test showed it: one `graphify update .` call grew a one-function fixture from 2 nodes/1 edge to 4 nodes/2 edges. The node ID of `lib.rs` is `src_lib_add` when scanned via `extract src`. It is `lib_add` when scanned via `update .`. Thus the cache never matches, and the file is added again as new. Every later SDD skill assumes the graph is correct. The override note keeps an sdd-unaware session that follows its CLAUDE.md from corrupting the graph.
8. Report which labels were created vs already present (the script's `created`/`present` lines). Also report whether the specs dir / graphify index were created or already existed.

## Common Mistakes
- Running `cp -r <dir>/graphify-out ./graphify-out` without first removing any existing `./graphify-out`. If the target already exists, `cp -r` nests the source inside it instead of replacing it, leaving the top-level graph stale. Always `rm -rf ./graphify-out` immediately before the copy.
- Running a single-root invocation (e.g. `graphify <source-dir> --no-viz`) when there's more than one source directory. Or assuming that its output lands at `<repo-root>/graphify-out/`: the CLI nests output inside whatever path you give it. Always go through the extract-per-directory + `merge-graphs` sequence in step 5, even for exactly one directory, so the output location is uniform.
- Scoping the corpus to the whole repo (including `docs/specs/`) — this silently starts costing LLM tokens on every doc change. Always scope to source dirs only.
- Picking a source directory that already contains a stray `.md` file (e.g. a `src/README.md`). `graphify extract` doesn't silently skip it. Without an LLM API key it errors ("no LLM API key found... need semantic extraction"). If a backend key happens to be set in the environment, it actually performs LLM extraction on it. Check chosen source directories for stray docs first, or exclude them, before running step 5.
- Not appending the override note in step 7. Without it, the very first ordinary Claude Code session that edits code in this repo follows its own CLAUDE.md. That session then runs the corrupting `graphify update .` command.
