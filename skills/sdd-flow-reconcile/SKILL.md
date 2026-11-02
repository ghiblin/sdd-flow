---
name: sdd-flow-reconcile
description: Use after a sdd-flow-tdd implementation pass, before considering a feature done or clearing/compacting the session, to check the spec against the code and persist a resumable checkpoint.
---

# Spec-Anchored Reconcile

**Helper paths:** every script and template this skill uses is shared across the sdd-flow plugin, at `${CLAUDE_PLUGIN_ROOT}/scripts/…` and `${CLAUDE_PLUGIN_ROOT}/templates/…`. `${CLAUDE_PLUGIN_ROOT}` is the plugin's own install directory, set by the Claude Code plugin runtime; it resolves the same way regardless of where the plugin is installed.

## Overview
The only safe point in the SDD loop to clear or compact the session. Everything needed to resume must be on the GitHub main issue before you tell the user it's safe to clear — not "mostly," not "I'll remember the rest."

## The rule

**Before this step reports done, the main issue MUST reflect: the `**Spec files:**` line matching what was touched, a sub-issue set whose open members are exactly the not-yet-built increments, and a `## Open decisions` block listing every still-open significant decision (unchecked) and no resolved one (or checked).** If any of those would be wrong or incomplete, the checkpoint has not been reached — do not tell the user it's safe to clear.

## Rationalization table

| Excuse | Reality |
|---|---|
| "It's a small gap, I'll just remember it" | The entire point of this checkpoint is that nothing depends on you remembering. Write it down. |
| "The user will re-explain if needed" | That's the exact per-feature-conversation cost this workflow was built to remove. |
| "Reconcile passed, close enough" | "Close enough" is an open sub-issue, not a pass. |
| "I'm confident the Architecture section is right, no need to re-check" | Confidence isn't the check — the whole reconcile step exists because "I'm confident" is where drift sneaks past. Run the graphify diff anyway. |
| "I updated the issue / spec files" (said without re-reading them back) | An assertion isn't a write. Read the issue back with `gh issue view` and the spec file off disk, and confirm the exact content you claimed is there before you say so. |

## Red flags — stop and fix before reporting done

- You're about to say "safe to clear" while a decision is still unresolved. It is in your head but not an unchecked line in the issue's `## Open decisions`.
- Every sub-issue looks closed but you haven't actually compared it against the original `intent`.
- A known follow-up piece of work has no open sub-issue to track it, because it "isn't part of this pass."
- You're about to report an issue or spec-file write as done. But you haven't re-read the issue with `gh issue view` (and the spec file off disk) since the change, in this same turn. Only that re-read confirms the write landed.

## Sub-issue helpers

`$n` = the main issue number (step 3). Every helper below is a stdlib Python script in `${CLAUDE_PLUGIN_ROOT}/scripts/`; each mutating one reads and writes UTF-8, refuses to write an empty body, re-reads the issue afterwards and exits non-zero if what landed does not match. A non-zero exit means stop and report it rather than retrying blindly. Keep dollar-plus-digit positional tokens (perl/shell capture references) out of this whole file: the skill loader substitutes the skill's arguments into them. The scripts' tests run with `python3 -m unittest discover -s "${CLAUDE_PLUGIN_ROOT}/scripts"`.

**Create + nest a sub-issue:**
```bash
child=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-sub-issue.py" "$n" --title "<increment>" [--needs-spec])
```
The body is `Part of #$n` (from `${CLAUDE_PLUGIN_ROOT}/templates/sub-issue.md`). A non-zero exit naming a child means the child exists but is not nested — report the un-nested child rather than dropping it. `--needs-spec` also adds the `sdd:needs-spec` label: the spec section does not describe that work yet, so `sdd-flow-draft` must write it before `sdd-flow-tdd` builds it. The script verifies the label on read-back.

**List the sub-issues that need a spec:**
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n"
```
Prints the number of each open sub-issue that carries `sdd:needs-spec`, one per line. No output means none.

Reconcile writes no new behaviour into the spec section. It only corrects drift (step 2) and records unspecced work as an `sdd:needs-spec` sub-issue (steps 3 and 4). Only `sdd-flow-draft` writes new behaviour, so the scenarios come from a session that does not implement them.

**Read completion:**
```bash
summary=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sub-issues-summary.py" "$n") || { echo "sub-issue summary failed" >&2; exit 1; }
read completed total <<< "$summary"; [ -n "$completed" ] && [ -n "$total" ] || { echo "empty sub-issue summary" >&2; exit 1; }
```
Prints `<completed> <total>` from the GraphQL `subIssuesSummary`. A failed or empty summary is a stop, never a pass (empty equals empty). Scope is clear when `completed == total` (`total == 0` also counts as clear).

## Steps

1. Refresh the graph. The project may have a graph refresh script (for example `scripts/graphify_refresh.py`). If so, run it without `--full`. It extracts only the directories that the branch diff touches. A failed extract leaves `./graphify-out` as it was. A non-zero exit is a stop. Without such a script, read `<repo-root>/.claude/sdd-source-dirs.json` for the directory list. Re-run `graphify extract <dir>` for each directory. Then unify as sdd-flow-init did. For two or more directories, run `merge-graphs` across all `graphify-out/graph.json` files. For exactly one, run `rm -rf ./graphify-out && cp -r <dir>/graphify-out ./graphify-out`. The `rm -rf` is not optional, because this step repeats every pass and `cp -r` into an existing target nests the source inside it. This is LLM-free by construction: `extract` never triggers semantic extraction, and the source directories never contain prose docs.
2. For each spec section touched this pass, diff its **Architecture**/**Decisions** against what graphify's query/explain actually reports for that module now. Patch the spec section's **Architecture** and **Decisions** to match reality. Fix stale file paths, module boundaries, and invariants that the code no longer honours. This is drift correction, not a rewrite of **Goal**. Change only spec text that the code contradicts. Keep text that describes the behaviour of an open sub-issue. That behaviour is not built yet, so missing code is not drift. If the project's governance docs cap a spec file's size, re-check each patched file against that cap. Split any file now over it the way those docs prescribe, in this pass. Add the new files to the `**Spec files:**` line (step 3). Interface signatures and test-file listings are not standing headings, so the spec file has nothing of that kind to reconcile. Read them from the code and from the project's test directories. Then commit the patched spec files, as `docs: <description> (#<n>)`. Then run the project's full build gate (from its governance docs) on that clean tree, after the commit. Use the project's gate script if it has one. Run the gate even when this step changes nothing, unless the last gate run was on this same tree. This is an instructed step, not one a hook enforces. Steps 3 and 5 need a clean tree: `close-sub-issue.py` refuses on a dirty one. So do not leave a file uncommitted before step 3.
3. **Resolve the main issue:** `n=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve-issue.py")`. On a non-zero exit, stop. Tell the user to run `sdd-flow-intent` or to check out the feature branch. Compare the (now-patched) spec section against the `**Intent:**` line. For each intent obligation not yet in the code, check that an open `sdd:task` sub-issue covers it. If none does, create a nested one with the **Sub-issue helpers** section above. If the obligation is not described in the spec section, add `--needs-spec` to that command. For each open sub-issue whose work is now done and gate-green, close it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/close-sub-issue.py" "$n" "$child"`, where `child` is its number. The script needs a clean tree. It also needs a `test:` commit before a `feat:` or `fix:` commit for the sub-issue, unless the sub-issue carries `sdd:no-red-green`. On a non-zero exit, the sub-issue stays open. Then report the reason to the user. Never close a sub-issue another way. Never send a close back to `sdd-flow-tdd`. Also make sure the `**Spec files:**` line (inside the `<!-- sdd:begin -->`/`<!-- sdd:end -->` markers) lists every spec file this pass touched, comma-separated. If a file was added since the issue was created, append it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-spec-files.py" "$n" --add --spec-file <path>`. Without `--add`, the line lists exactly the given `--spec-file` paths. Only that line changes.
4. For every significant decision from `sdd-flow-tdd` still unresolved, make sure it is an unchecked `- [ ] <question>` line in the main issue's `## Open decisions` block. Check off (`- [x]`) any that are now resolved. A resolved decision can add or change behaviour that the spec section does not describe. For each such decision that this pass checks off, create a new sub-issue whose title names that decision: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/create-sub-issue.py" "$n" --title "<decision>" --needs-spec`. Do this only in the pass that checks the decision off. A decision can be `- [x]` already when this pass starts. An earlier pass created its sub-issue, so create none for it. Also create none when a sub-issue, open or closed, already names that decision. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/list-sub-issues.py" "$n"` lists every sub-issue with its state and title. Never add the label to a sub-issue that existed before this pass. One exception is a repair. When the label of a new sub-issue does not land, `create-sub-issue.py` asks you to add it to that sub-issue. Then, if the project has a new public item check (for example `scripts/check_pub_items.py --issue "$n"`), run it. On exit 1, report each printed `UNRESOLVED` item. The pass does not end `complete` until a checked `- [x]` line in `## Open decisions` resolves each one.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add-open-decision.py" "$n" --question "<question>"
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check-open-decision.py" "$n" --question "<question>" [--resolved-as "<decision (who, date)>"]
   ```

   `add-open-decision.py` replaces the `- [ ] _none_` placeholder or appends the line. It skips the write if that exact question is already in the block, open or resolved. `check-open-decision.py` turns that question's `- [ ] <question>` into `- [x] <question>`, or `- [x] <question> → <decision (who, date)>` with `--resolved-as`, so a resolved line always keeps its question. It does nothing if the question is already checked (`[x]` or `[X]`, whatever the resolution). It exits non-zero if the exact question is not in the block. Prefixes never match, and trailing whitespace is ignored. Both scripts refuse `_none_`. `add-open-decision.py` also refuses a new question containing `→`. An existing open question with `→` can still be checked off; its resolved line writes that `→` as `->`. If the same question is both open and checked, the script checks off the open copy. Both read CRLF bodies as LF and share the block parsing in `open_decisions.py`. Never hand-edit the body with `perl`/`sed`: either can silently corrupt non-ASCII characters elsewhere in the body.
5. Set the stage in this order. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/needs-spec.py" "$n"`. Read `completed`/`total` per the **Sub-issue helpers** section above. If the helper prints a sub-issue → `drafting-spec`. Else, if `completed < total` (work still open) → `implementing`. Else (`completed == total`) → `complete`. Apply it with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/set-stage.py" "$n" <drafting-spec|implementing|complete>`, which swaps every other `sdd:stage:*` label for `sdd:stage:<stage>` and rewrites the `**Stage:**` body line to match.
6. **Verify, don't assert:** re-read `gh issue view "$n" --json labels,body` and the `subIssuesSummary` right now, in this same turn. Confirm the label, the `**Stage:**` line, the `**Spec files:**` line, the `## Open decisions` block, and the open/closed sub-issue set are exactly what you intended. If anything is off, fix it. Re-read again before continuing.
7. Step 2 committed the spec files, and steps 3 to 6 change only the issue. If a file is still uncommitted, commit it now. Then run the gate again (step 2).
8. If any open sub-issue carries `sdd:needs-spec`: the spec section does not describe that work yet, so the next stage is `sdd-flow-draft`, then `sdd-flow-tdd`. List the labelled sub-issues (step 5's `needs-spec.py` output) and the decisions they name. Recommend a fresh session. Give the exact resume prompt with the real numbers: `check out sdd/<n>-<slug>, read issue #<n>, run sdd-flow-draft for the sdd:needs-spec sub-issues #<a>, #<b>, then sdd-flow-tdd`. Only continue in this session if the user asks to.
9. Else, if any sub-issue is still open: tell the user what's left (list the open sub-issue titles). This is not the end of the feature, but it is a session boundary. Recommend a fresh session for the next increment. The spec section is already drafted and each sub-issue is an implementation increment, so the next stage is `sdd-flow-tdd`. Give the exact resume prompt: `check out sdd/<n>-<slug>, read issue #<n>, continue with sdd-flow-tdd for the next open sub-issue`. Only continue in this session if the user asks to.
10. If every sub-issue is closed and `## Open decisions` has no unchecked box: tell the user the feature is complete. Tell them to start a **fresh session** for `sdd-flow-pr-validate`, rather than continuing in this one. Give the exact resume prompt: `check out sdd/<n>-<slug>, read issue #<n>, run sdd-flow-pr-validate`.
11. If every sub-issue is closed but `## Open decisions` still has an unchecked box: the feature is not ready for `sdd-flow-pr-validate`, which refuses it. List the open decisions. Ask the user to resolve them. Give the exact resume prompt for a fresh session: `check out sdd/<n>-<slug>, read issue #<n>, resolve the open decisions, then run sdd-flow-reconcile`.

## Common Mistakes
- Treating reconcile as a one-time end-of-feature step instead of the loop's repeatable checkpoint. It runs every pass, not just the last one.
- Reporting an issue or spec-file write as done because the write call appeared to succeed, without step 6's re-read. A tool call returning without error is not the same as the content being correct.
- Skipping the `rm -rf ./graphify-out` before step 1's `cp -r` in the single-directory case, when no refresh script does it. This step repeats every pass, so the second and every later pass then silently nests instead of refreshing. Every subsequent `graphify query`/`explain` call in this step and in sdd-flow-intent's DDD check answers from a graph frozen at the first pass.
