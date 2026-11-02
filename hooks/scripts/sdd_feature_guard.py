#!/usr/bin/env python3
"""PreToolUse hook for `sdd-flow-implementer`: deny edits of BDD feature files.

Declared in the frontmatter of the `sdd-flow-implementer` agent definition (never in
`.claude/settings.json`), so the test author stays separate from the
implementer. It denies:

- an `Edit`, `Write` or `NotebookEdit` call on a `*.feature` path;
- a Bash command that writes to a `*.feature` path with a redirect (`>`, `>>`),
  `tee`, `sed -i`, `perl -i`, `cp` (onto a feature file, or a feature file into a
  directory), `mv`, `rm`, `touch`, `truncate`, `ln` (onto a feature file) or
  `dd of=`;
- an `rm -r` or `mv` of a directory that holds a feature file, and a `cp -r` of
  one into a path inside the working directory. Paths are relative to the hook
  input's `cwd`, moved by each plain `cd <dir>` or `pushd <dir>` earlier in the
  command. When the command has a pipe, and for a `cd` in `( ... )`, each `cd`
  target is one more candidate directory instead, and each candidate is
  checked. A `popd`, `cd -`, bare `pushd` or `pushd +N` adds every directory
  seen so far as a candidate. When no `pushd` (for `cd -`: no move) came
  before it in the command, it moves to a directory the hook cannot see, so a
  write command (`tee`, `rm`, `mv`, `touch`, `truncate`, `cp`, `ln`, `dd`,
  `rmdir`, `mkdir`, `install`, `rsync`), an in-place edit or a file redirect
  (also `>& file`; `>&2` and `2>&1` only duplicate a descriptor) after it is
  denied for the rest of the command. `pushd -n` and
  `popd -n` move nothing. A `cd` in the background moves nothing. `env -C`
  and `sudo -D` (also in a short-option cluster, and as `--chdir`) move the
  command that they run, and a heredoc fed to it. The source of an `mv` and
  the target of a `cp` or `ln` also come from `-t <dir>`, `-t<dir>`, `t` in a
  short-option cluster, `--target-directory <dir>` and
  `--target-directory=<dir>`; a `--` ends these options, and an `-S` in a cluster
  takes the rest of it as its suffix. BSD env's `-P`, `-L` and `-U` take a
  value. A wrapper's short-option cluster that ends in a
  letter that takes a value (`sudo -nu root`) takes the next word. A heredoc script is checked in each directory
  that the command visits. A glob
  operand is expanded there first. A `cp -r` target counts as inside when it is in a
  git work tree (outside git: under the hook input's `cwd`). A directory holds a feature file when
  `git ls-files --cached --others --exclude-standard` lists one in it, so
  ignored build output such as `target/` is never walked. Outside a git repo,
  a walk that skips `.git`, `target` and `node_modules` and stops after
  20000 files is used instead.

The command name is read after control words, prefix words (with their
options), variable assignments and the wrappers `env`, `sudo`, `nice`,
`timeout` and `stdbuf` with their options. The script of `env -S` (also inside
a short-option cluster such as `-iS`), with the
arguments after it, is read as an inner script. Each inner script is checked in
the directory of its own segment.

Commands that only read a feature file, and the `remove-wip.py` helper, stay
allowed. The hook reads Bash commands with the shell reader of
`shell_commands.py`: it reads the scripts of `bash -c` and `eval`, command
substitutions and a heredoc fed to a shell, but not a heredoc body that is data.
It guards against honest mistakes, not a determined bypass: a write that a
script, `python -c`, `xargs rm`, `git rm`, `git mv`, `git checkout` or
`git apply` makes is out of its reach.
On a denial the hook prints a `permissionDecision: deny` JSON object;
otherwise it prints nothing.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import functools
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

SHELL_COMMANDS = Path(__file__).resolve().with_name("shell_commands.py")
FILE_TOOLS = {"Edit": "file_path", "MultiEdit": "file_path", "Write": "file_path", "NotebookEdit": "notebook_path"}
MAX_NESTING = 5

# Wrappers that run the command after them: (their options that take a value,
# the number of plain words before the command).
WRAPPERS = {
    # `-P`, `-L` and `-U` take a value in BSD env (macOS).
    "env": ({"-u", "--unset", "-C", "--chdir", "-P", "-L", "-U"}, 0),
    "sudo": ({"-u", "--user", "-g", "--group", "-C", "--close-from", "-h", "--host", "-p", "--prompt", "-D", "--chdir", "-r", "--role", "-t", "--type", "-T", "--command-timeout", "-U", "--other-user"}, 0),
    "nice": ({"-n", "--adjustment"}, 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1),
    "stdbuf": ({"-i", "--input", "-o", "--output", "-e", "--error"}, 0),
}
# Wrapper options that run the command in another directory.
CHDIR = {"env": ("-C", "--chdir"), "sudo": ("-D", "--chdir")}
TARGET = ("-t", "--target-directory")
# Options of the prefix words that take a value (`exec -a <name>`).
PREFIX_VALUES = {"exec": {"-a"}}
# Commands that write files, for a command that runs in a directory the hook cannot see.
WRITE_COMMANDS = {"tee", "rm", "mv", "touch", "truncate", "cp", "ln", "dd", "rmdir", "mkdir", "install", "rsync"}
# The target of a descriptor duplication, move or close (`>&2`, `>&3-`, `>&-`).
FD_TARGET = re.compile(r"\d*-?")
# A directory-stack index (`pushd +1`, `popd -0`).
STACK_INDEX = re.compile(r"[+-]\d+")
ENV_SPLIT = ("-S", "--split-string")
# The short env options that take a value: an `S` after one of them is part of that value.
ENV_VALUE_LETTERS = {f[1] for f in WRAPPERS["env"][0] if len(f) == 2}
PIPE = re.compile(r"(?<![|>])\|(?![|&])")
WALK_SKIP = {".git", "target", "node_modules"}
WALK_LIMIT = 20000
# Short options, per command, that take the rest of the cluster (or the next word) as a value.
VALUE_LETTERS = {"sed": set("efl"), "gsed": set("efl"), "perl": set("MmIeECdDxFV")}
# perl options that take only optional digits, then more switches may follow (`-lpi`, `-0pi`).
DIGIT_LETTERS = {"perl": set("l0")}

REASON = (
    "The implementer does not edit BDD feature files ({path}). Remove a `@wip` tag "
    "with `remove-wip.py <feature file> --scenario \"<name>\"`. For a new or changed "
    "scenario, get the user's approval, then end the turn with a NEEDS_SCENARIO_CHANGE "
    "block, so that a fresh sdd-flow-spec-writer subagent makes the change."
)


UNKNOWN_REASON = (
    "A `popd` or `pushd +N` with no earlier `pushd` in this command, or a `cd -` with no earlier "
    "`cd` in it, moves to a directory from an earlier shell state that the hook cannot see, so a "
    "write after it in the same command is denied. Run the write in a separate command."
)


def _load_shell_commands():
    spec = importlib.util.spec_from_file_location("shell_commands", SHELL_COMMANDS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shell = _load_shell_commands()


def _is_feature(path: str) -> bool:
    return path.strip().lower().endswith(".feature")


def _redirect(token: str) -> bool:
    """A shell output redirect operator: `>`, `>>`, `>|`, `&>`, `&>>` (an fd number is its own token)."""
    return ">" in token and set(token) <= set("<>&|")


def _in_place(flag: str, name: str = "sed") -> bool:
    """A `-i` short flag (alone, with a suffix such as `-i.bak`, or in a cluster such as `-pi`) or `--in-place`.

    The cluster is read letter by letter: a letter that takes a value (`-e`, or
    perl's `-M`, `-I`) ends it, so `-Mstrict` or `-Ilib` is not an in-place flag.
    """
    if flag.startswith("--"):
        return flag.split("=", 1)[0] == "--in-place"
    if not flag.startswith("-") or len(flag) < 2:
        return False
    letters = flag[1:]
    value = VALUE_LETTERS.get(name, set())
    digits = DIGIT_LETTERS.get(name, set())
    k = 0
    while k < len(letters):
        c = letters[k]
        if c == "i":
            return True
        if c in value or not c.isalpha() and c not in digits:
            return False
        k += 1
        if c in digits:
            while k < len(letters) and letters[k].isalnum() and not letters[k].isalpha():
                k += 1
    return False


def _expand(operand: str, cwd: str) -> list[str]:
    """The operand, or the paths a glob operand matches under `cwd`."""
    if not any(ch in operand for ch in "*?["):
        return [operand]
    base = operand if os.path.isabs(operand) else os.path.join(cwd, operand)
    return sorted(glob.glob(base)) or [operand]


def _full(path: str, cwd: str) -> str:
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, os.path.expanduser(path)))


def _holds_feature(path: str, cwd: str) -> bool:
    """`path` (relative to `cwd`) is a directory with a tracked or untracked, not ignored, `*.feature` file below it."""
    return _dir_holds_feature(_full(path, cwd))


@functools.lru_cache(maxsize=256)
def _dir_holds_feature(full: str) -> bool:
    """One probe per directory and hook call, however many candidate directories name it."""
    if not os.path.isdir(full):
        return False
    try:
        result = subprocess.run(
            ["git", "-C", full, "ls-files", "--cached", "--others", "--exclude-standard", "--", ":(glob,icase)**/*.feature"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0:
        return bool(result.stdout.strip())
    return _walk_holds_feature(full)


def _walk_holds_feature(full: str) -> bool:
    """Outside a git repo: a walk that skips build and VCS directories and stops after WALK_LIMIT files."""
    seen = 0
    for _root, dirs, files in os.walk(full):
        dirs[:] = [d for d in dirs if d not in WALK_SKIP]
        if any(_is_feature(f) for f in files):
            return True
        seen += len(files)
        if seen > WALK_LIMIT:
            return False
    return False


def _under(full: str, base: str) -> bool:
    base = os.path.normpath(base)
    return full == base or full.startswith(base.rstrip(os.sep) + os.sep)


def _in_work_tree(path: str, cwd: str, root: str) -> bool:
    """`path` resolves inside a git work tree, or, outside git, inside the hook input's `cwd` (`root`)."""
    return _full_in_work_tree(_full(path, cwd), root)


@functools.lru_cache(maxsize=256)
def _full_in_work_tree(full: str, root: str) -> bool:
    probe = full
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        result = subprocess.run(
            ["git", "-C", probe, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        pass
    return _under(full, root)


def _option_step(tokens: list[str], j: int, takes_value: set[str], chdir_flags: tuple[str, ...] = ()) -> tuple[int, str | None]:
    """How many tokens the option at tokens[j] uses, and the directory it names when it is a chdir option.

    A short-option cluster is read letter by letter: the first letter that takes a
    value takes the rest of the cluster (`-Cdir`), or the next word when it ends
    the cluster (`-iC dir`, `-nu root`).
    """
    tok = tokens[j]
    nxt = tokens[j + 1] if j + 1 < len(tokens) else None
    if tok in takes_value:
        return 2, (nxt if tok in chdir_flags else None)
    if tok.startswith("--"):
        name, eq, value = tok.partition("=")
        return 1, (value if eq and name in chdir_flags else None)
    letters = {f[1] for f in takes_value if len(f) == 2 and f[1] != "-"}
    for k, c in enumerate(tok[1:]):
        if c in letters:
            rest = tok[k + 2 :]
            if rest:
                return 1, (rest if "-" + c in chdir_flags else None)
            return 2, (nxt if "-" + c in chdir_flags else None)
    return 1, None


def _skip_options(tokens: list[str], lead: int, takes_value: set[str], words: int = 0, chdir_flags: tuple[str, ...] = ()) -> tuple[int, str | None]:
    """The index after the options, assignments and `words` plain words that follow a wrapper, and its chdir directory."""
    chdir = None
    while lead < len(tokens):
        tok = tokens[lead]
        if tok == "--":
            lead += 1
            break
        if tok.startswith("-") and len(tok) > 1:
            step, value = _option_step(tokens, lead, takes_value, chdir_flags)
            chdir = value or chdir
            lead += step
        elif shell.ASSIGNMENT.match(tok):
            lead += 1
        else:
            break
    return min(lead + words, len(tokens)), chdir


def _command_start(tokens: list[str]) -> tuple[int, list[str], str | None]:
    """The index of the command name, the scripts of any `env -S` on the way, and the
    directory that an `env -C` or `sudo -D` on the way moves the command to."""
    scripts: list[str] = []
    chdir: str | None = None
    lead = 0
    while lead < len(tokens):
        tok = tokens[lead]
        name = shell._name(tok)
        if tok in shell.CONTROL_WORDS or shell.ASSIGNMENT.match(tok):
            lead += 1
        elif tok in shell.PREFIX_WORDS:
            lead, _ = _skip_options(tokens, lead + 1, PREFIX_VALUES.get(tok, set()))
        elif name in WRAPPERS:
            if name == "env":
                takes_value = WRAPPERS["env"][0]
                j = lead + 1
                while j < len(tokens):
                    tj = tokens[j]
                    split = None
                    if tj in ENV_SPLIT and j + 1 < len(tokens):
                        split, rest = tokens[j + 1], tokens[j + 2 :]
                    elif tj.startswith("--split-string="):
                        split, rest = tj.split("=", 1)[1], tokens[j + 1 :]
                    elif tj.startswith("-S") and len(tj) > 2:
                        split, rest = tj[2:], tokens[j + 1 :]
                    elif tj.startswith("-") and not tj.startswith("--") and "S" in tj[1:] and not (set(tj[1 : tj.index("S", 1)]) & ENV_VALUE_LETTERS):
                        # `-S` inside a short-option cluster (`-iS 'cmd'` or `-iScmd`)
                        after = tj[tj.index("S", 1) + 1 :]
                        if after:
                            split, rest = after, tokens[j + 1 :]
                        elif j + 1 < len(tokens):
                            split, rest = tokens[j + 1], tokens[j + 2 :]
                    if split is not None:
                        # env runs the split words followed by the rest of its arguments.
                        scripts.append(" ".join([split, shlex.join(rest)]).strip())
                        return len(tokens), scripts, chdir
                    if tj == "--":
                        j += 1
                        break
                    if tj.startswith("-") and len(tj) > 1:
                        step, value = _option_step(tokens, j, takes_value, CHDIR["env"])
                        chdir = value or chdir
                        j += step
                    elif tj == "-" or shell.ASSIGNMENT.match(tj):
                        j += 1
                    else:
                        break
                lead = j
                continue
            takes_value, words = WRAPPERS[name]
            lead, value = _skip_options(tokens, lead + 1, takes_value, words, CHDIR.get(name, ()))
            chdir = value or chdir
        else:
            break
    return lead, scripts, chdir


def _target(args: list[str]) -> str | None:
    """The directory of a `cp`/`mv`/`ln` target option: `-t <dir>`, `-t<dir>`, `t` in a
    short-option cluster (`-vt <dir>`), `--target-directory <dir>` or `--target-directory=<dir>`."""
    for j, a in enumerate(args):
        if a == "--":
            break
        if a in TARGET and j + 1 < len(args):
            return args[j + 1]
        if a.startswith("--target-directory="):
            return a.split("=", 1)[1]
        if a.startswith("-") and not a.startswith("--"):
            for k, c in enumerate(a[1:]):
                if c == "S":  # `-S <suffix>` takes the rest as its value
                    break
                if c == "t":
                    rest = a[k + 2 :]
                    return rest or (args[j + 1] if j + 1 < len(args) else None)
    return None


def _moved_to(chdir: str | None, cwd: str) -> str:
    """The directory that a wrapper's `-C`/`-D` moves a command to, or `cwd`."""
    return _full(chdir, cwd) if chdir and not shell._dynamic(chdir) else cwd


def _writes(tokens: list[str], cwd: str = ".", root: str | None = None, start: tuple[int, list[str], str | None] | None = None) -> str | None:
    """The feature path that one simple command writes, or None. `start` is the
    `_command_start` result when the caller has it already."""
    for i, tok in enumerate(tokens[:-1]):
        if _redirect(tok) and _is_feature(tokens[i + 1]):
            return tokens[i + 1]
    lead, _scripts, chdir = start if start is not None else _command_start(tokens)
    if lead >= len(tokens):
        return None
    cwd = _moved_to(chdir, cwd)
    name = shell._name(tokens[lead])
    args = tokens[lead + 1 :]
    operands = [path for a in args if not a.startswith("-") for path in _expand(a, cwd)]
    features = [a for a in operands if _is_feature(a)]
    if name in ("tee", "rm", "mv", "touch", "truncate") and features:
        return features[0]
    if name in ("sed", "gsed", "perl") and features and any(_in_place(a, name) for a in args):
        return features[0]
    recursive = any(a.startswith("-") and not a.startswith("--") and ("r" in a.lower() or "a" in a) or a in ("--recursive", "--archive") for a in args)
    if name == "rm" and recursive:
        held = next((a for a in operands if _holds_feature(a, cwd)), None)
        if held:
            return held
    if name == "mv":
        target = _target(args)
        sources = [a for a in operands if a != target] if target else operands[:-1]
        held = next((a for a in sources if _holds_feature(a, cwd)), None)
        if held:
            return held
    if name == "dd":
        out = next((a[3:] for a in args if a.startswith("of=")), "")
        if _is_feature(out):
            return out
    if name in ("cp", "ln"):
        target = _target(args)
        sources = [a for a in operands if a != target] if target else operands[:-1]
        target = target or (operands[-1] if len(operands) > 1 else "")
        if _is_feature(target):
            return target
        full = target if os.path.isabs(target) else os.path.join(cwd, target)
        if name == "cp" and target and (os.path.isdir(full) or target.endswith("/")):
            fed = next((s for s in sources if _is_feature(s)), None)
            if fed:
                return os.path.join(target, os.path.basename(fed))
        if name == "cp" and recursive and target and _in_work_tree(target, cwd, root or cwd):
            held = next((s for s in sources if _holds_feature(s, cwd)), None)
            if held:
                return target
    return None


def _may_write(tokens: list[str], start: tuple[int, list[str], str | None]) -> bool:
    """The simple command may write a file anywhere: a write command, an in-place edit or a file redirect."""
    for i, tok in enumerate(tokens[:-1]):
        # `>&2` and `2>&1` duplicate a file descriptor, `>&3-` moves one and `>&-`
        # closes one; `>& file` writes to a file.
        dup = tok.endswith("&") and FD_TARGET.fullmatch(tokens[i + 1]) is not None
        if _redirect(tok) and not dup and not tokens[i + 1].startswith("/dev/"):
            return True
    lead = start[0]
    if lead >= len(tokens):
        return False
    name = shell._name(tokens[lead])
    if name in WRITE_COMMANDS:
        return True
    return name in VALUE_LETTERS and any(_in_place(a, name) for a in tokens[lead + 1 :])


def _decide_scripts(scripts: list[str], level: int, cwd: str, root: str) -> str | None:
    if level >= MAX_NESTING:
        return None
    for script in scripts:
        reason = _decide_command(script, level + 1, cwd, root)
        if reason:
            return reason
    return None


def _decide_command(command: str, level: int = 0, cwd: str = ".", root: str | None = None) -> str | None:
    root = root or cwd
    text, heredocs = shell._split_heredocs(command)
    try:
        segments = shell._segments(text)
    except ValueError:
        segments = [shell.Segment(text.split(), False, False)]
    heredoc_scripts: list[str] = []
    for heredoc in heredocs:
        heredoc_scripts.extend(shell._heredoc_scripts(heredoc))
    # The directories a segment may run in. A plain `cd <dir>` (or `pushd <dir>`)
    # moves the shell, so it replaces them. A `cd` in a pipeline or in `( ... )`
    # runs in a subshell whose end the shell reader cannot see, so each such
    # `cd` target is added as one more candidate instead. A `popd`, `cd -` or
    # bare `pushd` adds every directory seen so far. A `cd` in the background
    # moves nothing.
    piped = bool(PIPE.search(text))
    cwds = [cwd]
    visited = [cwd]
    pushed = 0
    unknown = False
    for segment in segments:
        tokens = segment.tokens
        start = _command_start(tokens)
        lead, split_scripts, chdir = start
        if unknown and _may_write(tokens, start):
            return UNKNOWN_REASON
        inner = split_scripts + shell._inner_scripts(tokens)
        if chdir:
            # A heredoc fed to the command runs in its `env -C`/`sudo -D` directory.
            visited = list(dict.fromkeys(visited + [_moved_to(chdir, here) for here in cwds]))
        for here in cwds:
            path = _writes(tokens, here, root, start)
            if path:
                return REASON.format(path=path)
            # Each segment's inner scripts run in the directory of that segment
            # (and in the directory of its `env -C` or `sudo -D`, if any).
            for where in dict.fromkeys([here, _moved_to(chdir, here)]):
                reason = _decide_scripts(inner, level, where, root)
                if reason:
                    return reason
        name = shell._name(tokens[lead]) if lead < len(tokens) else ""
        if name in ("cd", "pushd", "popd") and not segment.background:
            args = tokens[lead + 1 :]
            if args[:1] == ["--"]:
                args = args[1:]
            rotate = any(STACK_INDEX.fullmatch(a) for a in args)
            dirs = [a for a in args if not a.startswith("-") and not STACK_INDEX.fullmatch(a)]
            if name != "cd" and "-n" in args:
                pass  # `pushd -n` and `popd -n` change only the stack, not the directory
            elif name == "popd" or args == ["-"] or name == "pushd" and (rotate or not dirs):
                # A return to an earlier directory. When this command moved before (with a
                # `pushd` for the stack, any move for `cd -`), every directory seen so far is
                # a candidate. Otherwise the directory comes from an earlier shell state that
                # the hook cannot see.
                known = pushed > 0 if name != "cd" else len(visited) > 1
                if not known:
                    unknown = True
                cwds = list(dict.fromkeys(cwds + visited))
                if name == "popd" and pushed:
                    pushed -= 1
            elif len(dirs) == 1 and not shell._dynamic(dirs[0]):
                moved = [_full(dirs[0], here) for here in cwds]
                adds = piped or segment.nested
                cwds = list(dict.fromkeys(cwds + moved)) if adds else list(dict.fromkeys(moved))
                visited = list(dict.fromkeys(visited + moved))
                if name == "pushd":
                    pushed += 1
    # A heredoc fed to a shell runs where its segment runs; check it in every
    # directory that the command visits.
    for here in visited:
        reason = _decide_scripts(heredoc_scripts, level, here, root)
        if reason:
            return reason
    return None


def decide(data: dict) -> str | None:
    """The deny reason for this tool call, or None to allow it."""
    _dir_holds_feature.cache_clear()
    _full_in_work_tree.cache_clear()
    name = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    if name in FILE_TOOLS:
        path = str(tool_input.get(FILE_TOOLS[name], ""))
        return REASON.format(path=path) if _is_feature(path) else None
    if name == "Bash":
        return _decide_command(str(tool_input.get("command", "")), cwd=str(data.get("cwd") or os.getcwd()))
    return None


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
