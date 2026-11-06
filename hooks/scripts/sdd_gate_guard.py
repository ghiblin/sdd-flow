#!/usr/bin/env python3
"""PreToolUse hook for the SDD agents: deny gate bypasses in Bash commands.

Declared in the frontmatter of the SDD agent definitions (never in
`.claude/settings.json`), so it applies only to SDD sessions. It denies a Bash
command that:

- runs `gh issue close` (sub-issues close only through `close-sub-issue.py`);
- runs `gh issue edit --add-label` or `gh issue create --label` naming
  `sdd:stage:spec-approved`, `sdd:stage:complete`, `sdd:stage:verified` or
  `sdd:no-red-green` (in any
  letter case, as GitHub label names are case-insensitive), or a label it
  cannot read because it holds a variable or a command substitution;
- runs `gh api` with a `closeIssue` or `addLabelsToLabelable` mutation, a
  `state=closed` field, a field that names a guarded label, or a write body
  from `--input` (which it cannot read); read-only queries stay allowed;
- runs a `gh` whose name or subcommand is a variable, or an `eval` of a variable;
- runs `set-stage.py <n> complete|verified` (or a stage it cannot read) when
  the target worktree is not clean, no gate marker matches its `HEAD^{tree}`
  (see `scripts/gate_marker.py`), the target worktree is unclear, or (while the
  project's `security_commands` config key is non-empty) no security marker
  matches that tree (see `scripts/run_security_commands.py`'s `sdd-security/<tree>`)
  or the hook's narrow, dedicated read of just that one config key fails.

The hook reads `gh` global flags (`-R`, `--repo`) before the subcommand, glued
short flags (`-lLABEL`), the scripts of `bash -c`/`sh -c`/`zsh -c` and `eval`,
and `$(...)` and backtick substitutions, quoted or not. A heredoc body is data,
except a body fed to a shell (`bash <<EOF`, `cat <<EOF | sh`), which it reads
whole, and the substitutions in a body with an unquoted delimiter.

The target worktree is the last `cd <dir>` before the `set-stage.py` call in
the same command, else the hook input's `cwd`. A `cd` inside a subshell, a
`{ }` group or an `if`/loop, after `||`, `command`, `builtin`, `time`, `nohup`
or `exec`, run in the
background (`&`), to a variable or to `-`, or a `pushd`/`popd`, makes the
target unclear, and the hook then denies a guarded `set-stage.py`.
The hook guards against honest mistakes, not a determined bypass: a static
reader of shell text cannot be complete (see issue #385 for the known gaps).
On a denial the hook prints a `permissionDecision: deny` JSON object;
otherwise it prints nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import NamedTuple

GUARDED_LABELS = (
    "sdd:stage:spec-approved",
    "sdd:stage:complete",
    "sdd:stage:verified",
    "sdd:no-red-green",
)
GUARDED_STAGES = ("complete", "verified")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
GH_VALUE_FLAGS = {"-R", "--repo", "--hostname"}
API_MUTATIONS = ("closeissue", "addlabelstolabelable")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
GATE_MARKER = SCRIPTS_DIR / "gate_marker.py"
SECURITY_RUNNER = SCRIPTS_DIR / "run_security_commands.py"
SDD_FLOW_CONFIG = SCRIPTS_DIR / "sdd_flow_config.py"
MAX_NESTING = 5

CLOSE_REASON = (
    "Raw issue closes are blocked in SDD sessions. Close an sdd:task sub-issue with "
    "the shared `${CLAUDE_PLUGIN_ROOT}/scripts/close-sub-issue.py <main> <child>` "
    "(sdd-flow-tdd and sdd-flow-reconcile both call it), which checks the gate marker and "
    "the red-green pair."
)
LABEL_REASON = (
    "Adding {labels} with a raw gh command is blocked in SDD sessions. Move stages "
    "with `set-stage.py` after the gate passes; set sdd:no-red-green only through an "
    "approved `create-sub-issue.py --no-red-green` or `needs-spec.py --clear <child> "
    "--no-red-green`. Write every label literally (no variable)."
)
GH_DYNAMIC_REASON = (
    "A gh command whose name or subcommand is a variable, or an `eval` of a variable, "
    "is blocked in SDD sessions: the hook cannot read it. Write the command literally."
)
CONTROL_WORDS = {"{", "}", "then", "do", "else", "elif", "if", "while", "until", "!"}
PREFIX_WORDS = {"command", "builtin", "time", "nohup", "exec"}


class Segment(NamedTuple):
    tokens: list[str]
    nested: bool  # inside `( ... )` or `$( ... )`
    after_or: bool  # runs only if the command before it failed
    background: bool = False  # ends with `&`, so it runs in a subshell


class Heredoc(NamedTuple):
    opener: str  # the line that holds the `<<` operator
    body: str
    quoted: bool  # a quoted delimiter: the shell expands nothing in the body


def _split_heredocs(command: str) -> tuple[str, list[Heredoc]]:
    """The command without heredoc bodies, and each body with the line that opens it."""
    out: list[str] = []
    bodies: list[Heredoc] = []
    pending: list[tuple[bool, str, bool, str]] = []
    lines: list[str] = []
    for line in command.split("\n"):
        if pending:
            strip_tabs, delim, quoted, opener = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                bodies.append(Heredoc(opener, "\n".join(lines), quoted))
                lines = []
                pending.pop(0)
            else:
                lines.append(line)
            continue
        out.append(line)
        pending.extend((t, d, q, line) for t, d, q in _heredoc_starts(line))
    if pending:
        bodies.append(Heredoc(pending[0][3], "\n".join(lines), pending[0][2]))
    return "\n".join(out), bodies


def _heredoc_starts(line: str) -> list[tuple[bool, str, bool]]:
    """The (strip-tabs, delimiter, quoted) of each unquoted `<<` heredoc operator in a line.

    A `<<` inside quotes, a `<<<` here-string and an arithmetic shift in
    `$(( ... ))` or `(( ... ))` are not heredocs.
    """
    found: list[tuple[bool, str, bool]] = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "\\":
            i += 2
            continue
        elif ch in "'\"":
            quote = ch
        elif line.startswith("<<", i) and not line.startswith("<<<", i):
            if line[:i].count("((") > line[:i].count("))"):
                i += 2
                continue
            match = re.match(r"<<(-?)[ \t]*(['\"]?)([A-Za-z0-9_.-]+)\2", line[i:])
            if match:
                found.append((match.group(1) == "-", match.group(3), bool(match.group(2))))
                i += match.end()
                continue
        i += 1
    return found


def _substitutions(text: str) -> list[str]:
    """The body of each `$( ... )` and backtick substitution in a text (quoted or not)."""
    found: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("$((", i):
            i += 3
        elif text.startswith("$(", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            found.append(text[i + 2 : j - 1 if depth == 0 else j])
            i = j
        elif text[i] == "`":
            j = text.find("`", i + 1)
            found.append(text[i + 1 :] if j == -1 else text[i + 1 : j])
            i = len(text) if j == -1 else j + 1
        else:
            i += 1
    return found


def _strip_comment(line: str) -> str:
    """The line without its shell comment: a `#` outside quotes at the start of a word.

    A `#` inside a word (`issue#5`) is a literal character in the shell, so it stays.
    """
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "\\":
            i += 2
            continue
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t;&|()"):
            return line[:i]
        i += 1
    return line


def _segments(command: str) -> list[Segment]:
    """Split a shell command into simple commands, with their nesting and operator context."""
    text = " ; ".join(_strip_comment(line) for line in command.split("\n"))
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[Segment] = []
    current: list[str] = []
    depth = 0
    after_or = False
    for token in lexer:
        if token and set(token) <= set("&|;()"):
            if current:
                segments.append(Segment(current, depth > 0, after_or))
                current = []
            ops = token.replace("(", "").replace(")", "")
            if ops == "&" and segments:
                segments[-1] = segments[-1]._replace(background=True)
            depth = max(depth + token.count("(") - token.count(")"), 0)
            if ops:
                after_or = "||" in ops
            continue
        if token.endswith("$") and len(token) > 1:
            # `x=$(...)`: the `$` stays glued to the word before the `(`.
            token = token[:-1]
        if token != "$":
            current.append(token)
    if current:
        segments.append(Segment(current, depth > 0, after_or))
    return segments


def _name(token: str) -> str:
    return os.path.basename(token.strip("`"))


def _dynamic(text: str) -> bool:
    return "$" in text or "`" in text


def _gh_calls(tokens: list[str]) -> list[tuple[list[str], list[str]]]:
    """Each `gh` call in a simple command: (its first two subcommand words, every token after gh)."""
    calls = []
    for i, tok in enumerate(tokens):
        if _name(tok) != "gh":
            continue
        rest = [t.strip("`") for t in tokens[i + 1 :]]
        words: list[str] = []
        j = 0
        while j < len(rest) and len(words) < 2:
            if rest[j] in GH_VALUE_FLAGS:
                j += 2
            elif rest[j].startswith("-"):
                j += 1
            else:
                words.append(rest[j].lower())
                j += 1
        calls.append((words, rest))
    return calls


def _flag_values(tokens: list[str], flags: tuple[str, ...], split: bool = True) -> list[str]:
    """The values of `flags`: `--flag VALUE`, `--flag=VALUE`, `-f VALUE` and a glued `-fVALUE`."""
    values: list[str] = []
    for i, tok in enumerate(tokens):
        if tok in flags:
            if i + 1 < len(tokens):
                values.append(tokens[i + 1])
            continue
        for flag in flags:
            if flag.startswith("--"):
                if tok.startswith(flag + "="):
                    values.append(tok.split("=", 1)[1])
            elif not tok.startswith("--") and tok.startswith(flag) and len(tok) > len(flag):
                values.append(tok[len(flag) :])
    if split:
        values = [part for value in values for part in value.split(",")]
    return [v.strip() for v in values]


def _label_hits(labels: list[str]) -> list[str]:
    hits = {label.lower() for label in labels if label.lower() in GUARDED_LABELS}
    hits |= {label for label in labels if _dynamic(label)}
    return sorted(hits)


def _api_reason(rest: list[str]) -> str | None:
    """Deny a `gh api` write that closes an issue or adds a guarded label.

    Only field values are read, so a read-only query (an endpoint with
    `?state=closed`, a GraphQL query without `mutation`) is allowed. A body
    from `--input` cannot be read, so a write with `--input` is denied.
    """
    fields = [f.lower() for f in _flag_values(rest, ("-f", "-F", "--field", "--raw-field"), split=False)]
    method = [m.upper() for m in _flag_values(rest, ("-X", "--method"))]
    if _flag_values(rest, ("--input",)) and not (method and all(m == "GET" for m in method)):
        return (
            "`gh api --input` is blocked in SDD sessions: the hook cannot read the body. "
            "Pass the fields with -f/-F, or use the skill's helper script."
        )
    if method and all(m == "GET" for m in method):
        return None  # a GET sends its fields as query parameters: a read
    for field in fields:
        if field.startswith("query=") and "mutation" not in field:
            continue
        if any(m in field for m in API_MUTATIONS) or re.match(r"state\s*=\s*closed", field):
            return CLOSE_REASON
        if "updateissue" in field and ("closed" in field or "labelids" in field):
            return CLOSE_REASON if "closed" in field else LABEL_REASON.format(labels="labels by id")
        hit = sorted({label for label in GUARDED_LABELS if label in field})
        if hit:
            return LABEL_REASON.format(labels=", ".join(hit))
    return None


def _gh_reason(tokens: list[str]) -> str | None:
    for i, tok in enumerate(tokens[:-1]):
        if _dynamic(tok) and tokens[i + 1].lower() in ("issue", "api"):
            return GH_DYNAMIC_REASON
    for words, rest in _gh_calls(tokens):
        if any(_dynamic(w) for w in words[:1]) or (words[:1] == ["issue"] and any(_dynamic(w) for w in words)):
            return GH_DYNAMIC_REASON
        if words == ["issue", "close"]:
            return CLOSE_REASON
        if words == ["issue", "edit"]:
            hit = _label_hits(_flag_values(rest, ("--add-label",)))
        elif words == ["issue", "create"]:
            hit = _label_hits(_flag_values(rest, ("--label", "-l")))
        elif words[:1] == ["api"]:
            reason = _api_reason(rest)
            if reason:
                return reason
            continue
        else:
            continue
        if hit:
            return LABEL_REASON.format(labels=", ".join(hit))
    return None


def _set_stage_target(tokens: list[str]) -> str | None:
    for i, tok in enumerate(tokens):
        if _name(tok) == "set-stage.py":
            args = [a for a in tokens[i + 1 :] if not a.startswith("-")]
            if len(args) >= 2 and (args[1].lower() in GUARDED_STAGES or _dynamic(args[1])):
                return args[1]
    return None


def _inner_scripts(tokens: list[str]) -> list[str]:
    """The script text of each `sh -c '<script>'`, `eval <args>` and substitution in a simple command."""
    scripts: list[str] = []
    for i, tok in enumerate(tokens):
        name = _name(tok)
        if name == "eval":
            scripts.append(" ".join(tokens[i + 1 :]))
        elif name in SHELLS:
            for j in range(i + 1, len(tokens) - 1):
                flag = tokens[j]
                if flag.startswith("-") and not flag.startswith("--") and "c" in flag[1:]:
                    scripts.append(tokens[j + 1])
                    # A script that is one variable (`"$X"`) cannot be read: treat it as an eval of a variable.
                    if re.fullmatch(r"\s*\$(\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)\s*", tokens[j + 1]):
                        scripts.append("eval \"$DYNAMIC\"")
                    break
        if "$(" in tok or tok.count("`") >= 2:
            scripts.extend(_substitutions(tok))
    return scripts


def _heredoc_scripts(heredoc: Heredoc) -> list[str]:
    """The parts of a heredoc body that run as commands.

    A body fed to a shell (`bash <<EOF`, `cat <<EOF | sh`) runs whole. A body
    with an unquoted delimiter still runs its `$( ... )` and backtick substitutions.
    """
    try:
        opener = [t for s in _segments(heredoc.opener) for t in s.tokens]
    except ValueError:
        opener = heredoc.opener.split()
    if any(_name(t) in SHELLS or _name(t) == "eval" for t in opener):
        return [heredoc.body]
    return [] if heredoc.quoted else _substitutions(heredoc.body)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gate_passed(repo: str) -> bool:
    try:
        return _load_module("gate_marker", GATE_MARKER).check(Path(repo))
    except Exception:
        return False


def _security_commands(repo: Path) -> list:
    """A narrow, dedicated read of just the `security_commands` key: the frontmatter
    reader without `sdd_flow_config.load()`'s `_validate()`, so a malformed, unrelated
    key elsewhere in the file (for example a `tiers.classification` typo) never affects
    this check. Missing config file or missing key: empty list, the documented default.
    Raises on a genuine read/parse failure of the frontmatter itself; the caller treats
    that as fail-closed, the same as `_gate_passed`'s own except-Exception."""
    config = _load_module("sdd_flow_config", SDD_FLOW_CONFIG)
    path = repo / config.DEFAULT_CONFIG_PATH
    if not path.is_file():
        return []
    parsed = config._parse_frontmatter(config._frontmatter_text(path))
    return parsed.get("security_commands") or []


def _security_ok(repo: str) -> bool:
    """True unless `security_commands` is configured but no security marker matches
    the clean tree, or the narrow read of `security_commands` itself fails."""
    try:
        commands = _security_commands(Path(repo))
    except Exception:
        return False
    if not commands:
        return True
    try:
        runner = _load_module("run_security_commands", SECURITY_RUNNER)
        tree = runner.tree_if_clean(Path(repo))
        return tree is not None and runner.marker_path(Path(repo), tree).is_file()
    except Exception:
        return False


def _decide_command(command: str, cwd: str, level: int = 0) -> str | None:
    text, heredocs = _split_heredocs(command)
    try:
        segments = _segments(text)
    except ValueError:
        segments = [Segment(text.split(), False, False)]
    if level < MAX_NESTING:
        for heredoc in heredocs:
            for script in _heredoc_scripts(heredoc):
                reason = _decide_command(script, cwd, level + 1)
                if reason:
                    return reason
    unclear = False
    for segment in segments:
        tokens = segment.tokens
        lead = 0
        while lead < len(tokens) and (
            tokens[lead] in CONTROL_WORDS or tokens[lead] in PREFIX_WORDS or ASSIGNMENT.match(tokens[lead])
        ):
            lead += 1
        conditional = any(t in CONTROL_WORDS or t in PREFIX_WORDS for t in tokens[:lead])
        # Only assignments or keywords (`x="$(...)"`): no command name, but substitutions still run.
        head = _name(tokens[lead]) if lead < len(tokens) else ""
        if head in ("pushd", "popd"):
            unclear = True
            continue
        if head == "cd":
            args = [a for a in tokens[lead + 1 :] if not a.startswith("-") or a == "-"]
            if (
                conditional
                or segment.nested
                or segment.after_or
                or segment.background
                or len(args) != 1
                or args[0] == "-"
                or _dynamic(args[0])
            ):
                unclear = True
            else:
                cwd = os.path.join(cwd, os.path.expanduser(args[0]))
            continue
        if "cd" in tokens[lead + 1 :] or "pushd" in tokens[lead + 1 :]:
            unclear = True
        if head == "eval" and any(_dynamic(t) for t in tokens[lead + 1 :]):
            return GH_DYNAMIC_REASON
        reason = _gh_reason(tokens)
        if reason:
            return reason
        stage = _set_stage_target(tokens)
        if stage:
            if unclear:
                return (
                    f"`set-stage.py ... {stage}` is blocked: the hook cannot tell which "
                    "worktree it targets. Run it as `cd <worktree> && python3 .../set-stage.py "
                    "<n> <stage>`, with no subshell, group, `if`, `||`, `&`, `pushd` or "
                    "variable around the `cd`."
                )
            if not _gate_passed(cwd):
                return (
                    f"`set-stage.py ... {stage}` is blocked: the worktree {cwd} is not "
                    "clean or no gate marker matches its HEAD^{tree}. Commit, then run "
                    "`scripts/check.sh` in that worktree."
                )
            if not _security_ok(cwd):
                return (
                    f"`set-stage.py ... {stage}` is blocked: the worktree {cwd} has a "
                    "configured `security_commands` key but no security marker matches "
                    "its HEAD^{tree} (or the hook could not read security_commands). Run "
                    "`scripts/run_security_commands.py` in that worktree."
                )
        if level < MAX_NESTING:
            for script in _inner_scripts(tokens):
                reason = _decide_command(script, cwd, level + 1)
                if reason:
                    return reason
    return None


def decide(data: dict) -> str | None:
    """The deny reason for this tool call, or None to allow it."""
    if data.get("tool_name") != "Bash":
        return None
    command = str((data.get("tool_input") or {}).get("command", ""))
    cwd = str(data.get("cwd") or os.getcwd())
    return _decide_command(command, cwd)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    reason = decide(data) if isinstance(data, dict) else None
    if reason:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
