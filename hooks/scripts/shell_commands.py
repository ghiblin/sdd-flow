#!/usr/bin/env python3
"""A small, static Bash-command reader shared by sdd-flow's PreToolUse hooks.

Not a hook itself — a library a hook imports (`importlib.util.spec_from_file_location`,
since hook scripts are loaded as files, not as an installed package) to answer "what does
this one Bash command actually do": split it into simple commands with their nesting and
operator context, read heredoc bodies and `$( ... )`/backtick substitutions, and resolve a
token to its command name. A hook built on this can then ask its own question (for example
`sdd_feature_guard.py`'s "does any of this write a `*.feature` file") without re-deriving
shell-parsing from scratch.

Reads `bash -c`/`sh -c`/`zsh -c` and `eval` scripts, and substitutions, quoted or not. A
heredoc body is data, except a body fed to a shell (`bash <<EOF`, `cat <<EOF | sh`), which
is read whole, and the substitutions inside a body with an unquoted delimiter. This is a
static reader of shell text, not a shell: it guards against honest mistakes, not a
determined bypass.
"""

from __future__ import annotations

import re
import shlex
from typing import NamedTuple

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
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
    import os

    return os.path.basename(token.strip("`"))


def _dynamic(text: str) -> bool:
    return "$" in text or "`" in text


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
