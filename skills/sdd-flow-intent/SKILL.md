---
name: sdd-flow-intent
description: Use when starting work on a new feature or change under the SDD workflow, before drafting any spec or writing code.
---

# Spec-Anchored Intent

**Helper paths:** `<base>` stands for this skill's base directory — the path on the `Base directory for this skill:` line the skill loader prints above this text. Substitute it literally wherever a command or path below names `<base>/scripts/…` or `<base>/templates/…`; never rewrite it as a repo-relative path, so the same text works from the repo copy and from the global `~/.claude/skills` copy.

## Overview
Turns a one- or two-sentence intent into: a DDD context (does this entity/module exist, what's its current shape), a target spec file, a complexity decision, and a **GitHub main issue** to resume from later.

## Steps

1. **State intent.** One or two sentences (e.g. "add a router pattern to the agent loop"). Reject vaguer input — ask the user to sharpen it first.
2. **DDD check.** Query the graphify graph for the entity/module named or implied by the intent: `graphify query "<intent>"` and/or `graphify explain "<ModuleName>"`. Determine: does it already exist, what's its current bounded context, what does it currently expose (callers/callees, public API). Do not open source files to answer this: the graph query is the answer. Read a file only if the graph has no match at all.
3. **Resolve target spec file(s).** One file per module/bounded-context lives at `docs/specs/<module-slug>.md`. If the project groups specs into topic folders, it lives at `docs/specs/<topic>/<module-slug>.md` instead. Pick `<topic>` by the project's documented folder rule (a feature spanning two topics gets one file in each). Reuse the existing file if the module already has one; otherwise this intent creates it. An intent may touch more than one module — list all of them.
4. **Complexity gate.** If the intent decomposes into independent pieces (each buildable and testable on its own), stop here. Hand off with this **REQUIRED SUB-SKILL:** use `superpowers:using-git-worktrees` to create one worktree per piece. Then use `superpowers:subagent-driven-development` or `superpowers:dispatching-parallel-agents` to run each piece through this same workflow independently. Otherwise continue as a single task. Each independent piece gets its **own** `sdd-flow-intent` run and its own main issue — pieces are never sub-issues of a shared epic. (Sub-issues are development increments under one worktree, created later by `sdd-flow-tdd`.)
5. **Create the main issue.** Choose `<feature-slug>` as a short kebab-case name for the intent.

   **Preconditions:** `gh auth status` green and a GitHub `origin`. If the first `gh` call fails on auth, stop. Tell the user to run `gh auth login`.

   Run the helper from the repo root; it prints the new issue's number:

   ```bash
   number=$(python3 "<base>/scripts/create-issue.py" \
     --slug "<feature-slug>" --intent "<the one/two sentence intent>" \
     --spec-file <spec-file path from step 3> \
     --decision "<significant question the intent already raises>")
   ```

   Repeat `--spec-file` once per path from step 3. Repeat `--decision` once per question. With no questions, omit `--decision`; the block then reads `- [ ] _none_`. The script renders `<base>/templates/main-issue.md`, the `<!-- sdd:begin -->`…`<!-- sdd:end -->` block. No line of it has leading whitespace, because later skills match its lines anchored at `^`. The script creates the issue with `sdd:feature` + `sdd:stage:drafting-spec`. It rewrites the body once with `**Branch:** sdd/<number>-<slug>`. Then it re-reads the issue. A non-zero exit means the body or labels did not land. Stop. Do not retry blindly. Report the failure. Its tests run with `python3 -m unittest discover -s "<base>/scripts"`.

   The branch `sdd/<issue-number>-<slug>` is created later by `sdd-flow-draft` via `superpowers:using-git-worktrees`; it is only *named* here. Do not create the worktree in this skill.

## Common Mistakes
- Skipping the graphify query and grepping/opening files instead — defeats the entire point of the index.
- Creating a new spec file when an existing module file already covers this area. Always check `docs/specs/` first (and every topic folder, if the project has them).
- Creating the worktree/branch in this skill — `sdd-flow-intent` only *names* the branch (`sdd/<number>-<slug>`); `sdd-flow-draft` creates it.
