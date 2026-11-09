#!/usr/bin/env python3
"""Run a project's configured `security_commands` on the clean tree, and write the
security marker for the step.

`sdd-flow-tdd` step 8 and `sdd-flow-pr-validate` step 3 each call this right after the
project's own build-gate command passes, on every build gate invocation. Each configured
`{name, run}` shell command (SAST, dependency audit, secret scan, ...) runs in turn; its
own exit code is the only pass/fail signal sdd-flow reads (see `sdd_flow_config.py`'s
`security_commands` key). A project sets its own severity threshold via each command's own
CLI flags.

When `security_commands` is empty (the default), this runs no command and writes no
marker — the gate doesn't need one (see `sdd_gate_guard.py`'s unconfigured case).

When every command exits zero, the step re-checks that the tree is still clean and
`HEAD^{tree}` is unchanged from the start of the run, exactly like `gate_marker.py`'s
`write()` does for the build-gate marker. A command that exits zero but leaves the tree
dirty (for example by writing a report into a tracked path), or that commits new content
mid-run, gets no marker written for either tree — the marker's absence is what later
blocks `set-stage.py <n> complete|verified`, the same mechanism as the build-gate marker.
A non-zero exit from any command is the actual gate failure, reported as such regardless
of marker state.

The marker sits at a sibling path to the existing build-gate marker
(`scripts/gate_marker.py`, `sdd-gate/<tree>`): `sdd-security/<tree>`, in the worktree's own
git dir, never committed. The path and write/check logic are deliberately duplicated here
rather than imported from `gate_marker.py` (whose `MARKER_DIR` is hardcoded to
`sdd-gate`) — the same duplicate-and-document-sync convention `close-sub-issue.py` already
uses for the build-gate marker; keep this in step with `gate_marker.py`'s own
`marker_path`.

Usage:
    scripts/run_security_commands.py [--repo DIR]
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MARKER_DIR = "sdd-security"
HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sdd_flow_config = _load("sdd_flow_config", "sdd_flow_config.py")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def tree_if_clean(repo: Path) -> str | None:
    """HEAD^{tree} when the working tree is clean, else None."""
    if _git(repo, "status", "--porcelain"):
        return None
    return _git(repo, "rev-parse", "HEAD^{tree}")


def marker_path(repo: Path, tree: str) -> Path:
    path = Path(_git(repo, "rev-parse", "--git-path", f"{MARKER_DIR}/{tree}"))
    return path if path.is_absolute() else (Path(repo) / path).resolve()


def _write_marker(repo: Path, tree: str) -> None:
    path = marker_path(repo, tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = _git(repo, "rev-parse", "HEAD")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(f"{head} {stamp}\n", encoding="utf-8")


def run(repo: Path | str = ".") -> tuple[bool, str]:
    """Run every configured security command on `repo`'s clean tree.

    Returns `(ok, message)`. `ok` is False only when a configured command exits
    non-zero — the gate's actual failure signal, same as a failing build-gate command.
    When every command exits zero, `ok` is True regardless of whether the marker got
    written: a dirty or changed tree at the end only withholds the marker.
    """
    repo = Path(repo)
    commands: list[dict[str, Any]] = sdd_flow_config.load_security_commands(repo)
    if not commands:
        return True, "no security_commands configured; nothing to run"
    tree = tree_if_clean(repo)
    for entry in commands:
        name = entry.get("name") or entry.get("run") or "<unnamed>"
        cmd = entry.get("run", "")
        if not cmd:
            # An empty `run` (a missing/blank field, often a typo) is not a scan that
            # ran and passed. `sh -c ""` itself exits 0, so left unchecked this would
            # be indistinguishable from a real pass and still get the trust marker.
            return False, f"security command {name!r} has no 'run' command configured"
        result = subprocess.run(cmd, shell=True, cwd=str(repo))
        if result.returncode != 0:
            return False, f"security command {name!r} exited {result.returncode}"
    if tree is None:
        return True, "security commands passed, but the tree was not clean at the start; no security marker written"
    after = tree_if_clean(repo)
    if after is None:
        return True, "security commands passed, but the tree is dirty at the end; no security marker written"
    if after != tree:
        return True, "security commands passed, but HEAD^{tree} changed during the run; no security marker written"
    _write_marker(repo, after)
    return True, f"security marker written for tree {after}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    ok, message = run(args.repo)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
