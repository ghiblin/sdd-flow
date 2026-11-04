---
name: sdd-flow
description: Use to start or resume the sdd-flow orchestrator from inside an existing Claude Code session, as an alternative to launching a separate `claude --agent sdd-flow` process. Invoke with a one- or two-sentence intent for a new feature, or `#<issue-number>` to resume one already in flight.
---

# SDD orchestrator (wrapper)

## Overview

A thin entry point to the `sdd-flow` orchestrator agent (`agents/sdd-flow.md`), for when you're already in a Claude Code session and don't want to drop to a terminal and run `claude --agent sdd-flow "<intent>"`. This skill does none of the orchestration itself — it dispatches the real orchestrator agent and gets out of the way. The orchestrator asks the user every question itself (`AskUserQuestion`, `PushNotification`); this skill never answers on its behalf and never predicts its outcome.

## Steps

1. **Resolve the argument.** Use the text passed to this skill as-is, unchanged:
   - `#<n>` or a bare number → resume issue `<n>`.
   - Anything else → a new intent (one or two sentences).
   If no argument was given, ask the user directly which of the two they want. Do not guess, and do not sharpen or reword an intent yourself — that elicitation is `sdd-flow-intent`'s job, run by the orchestrator's first stage.
2. **Dispatch the orchestrator.** Call the Agent tool once, `subagent_type: "sdd-flow"`, with the prompt set to exactly the resolved argument from step 1 — verbatim, since the orchestrator's own `## Input` section parses that exact string. Do not pass an `isolation` option: the orchestrator manages its own worktree-per-feature inside the current main checkout, and an isolated worktree here would fight that.
3. **Wait.** The dispatched orchestrator owns the whole interaction from here — every question it needs answered reaches the user through its own tool calls, across however many rounds the pipeline takes. This skill has no role in that loop. Do not relay, summarize, or answer any of it yourself; just wait for the dispatched agent's run to end.
4. **Report the outcome.** Relay the dispatched agent's final message to the user verbatim. If it printed a resume command (`claude --agent sdd-flow "#<n>"`), keep that line as-is and add that the same resume also works by invoking this skill again with the same `#<n>` argument.

## Common Mistakes

- Answering a question the dispatched orchestrator raises, or deciding to skip one because it looks obvious — every question must still reach the real user, exactly as `agents/sdd-flow.md` requires of its own subagents.
- Rewording, sharpening, or re-punctuating the intent/issue argument before passing it on — forward it unchanged so the orchestrator's `## Input` parsing sees exactly what the user typed.
- Adding any pipeline/orchestration logic to this file. It exists only to dispatch; all orchestration behavior belongs in `agents/sdd-flow.md`, and duplicating it here would only let the two drift apart.
