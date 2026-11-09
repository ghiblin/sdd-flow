#!/usr/bin/env python3
"""Close an `sdd:task` sub-issue only when the gate (and, if configured, the security
scan) passed on this tree and red came before green.

Usage:
  close-sub-issue.py <main-issue-number> <child> [--base main] [--repo .]

This is the only way to close a sub-issue. It refuses (exit 1, reason on stderr) unless:
`<child>` is an open `sdd:task` sub-issue of `<main>`; the working tree is clean (no tracked
change and no untracked, unignored file); a gate marker
`$(git rev-parse --git-path sdd-gate/<tree>)` matches `HEAD^{tree}` (written by the project's
gate script on a clean pass); if the project's `security_commands` key (read narrowly, the
same as `sdd_gate_guard.py`'s own check) is non-empty, a security marker
`$(git rev-parse --git-path sdd-security/<tree>)` also matches `HEAD^{tree}` (written by
`run_security_commands.py` on a clean pass); and, unless the sub-issue carries
`sdd:no-red-green`, `verify_red_green.py` finds a non-empty `test:` commit before a
`feat:`/`fix:` commit for `(#<child>)` in `<base>...HEAD`. Then it runs `gh issue close <child>
--reason completed` and re-reads the sub-issue, failing if its state is not CLOSED. Stdlib
only; importable (`close`, `main`).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER_DIR = "sdd-gate"
EXEMPT = "sdd:no-red-green"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lister = _load("list_sub_issues", "list-sub-issues.py")
_red_green = _load("verify_red_green", "verify_red_green.py")
_security_runner = _load("run_security_commands", "run_security_commands.py")
_config = _load("sdd_flow_config", "sdd_flow_config.py")
run_gh = _lister.run_gh


def sub_issues(parent: int) -> list[dict]:
    return _lister.list_sub_issues(parent)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def marker_file(repo: Path, tree: str) -> Path:
    """The gate marker path for `tree`, laid out as the project's gate script writes it.

    Keep this in step with `marker_path` in the project's `scripts/gate_marker.py`;
    `scripts/test_gate_marker.py` (`MarkerLayoutAgrees`) checks that both give the same path.
    """
    path = Path(_git(repo, "rev-parse", "--git-path", f"{MARKER_DIR}/{tree}"))
    return path if path.is_absolute() else (Path(repo) / path).resolve()


def _view(child: int) -> dict:
    return json.loads(run_gh(["issue", "view", str(child), "--json", "state,labels"]))


def close(parent: int, child: int, repo: Path | str = ".", base: str = "main") -> tuple[bool, str]:
    """Return (ok, message); close `child` only if every check passes."""
    repo = Path(repo)
    if not any(s["number"] == child for s in sub_issues(parent)):
        return False, f"#{child} is not a sub-issue of #{parent}"
    issue = _view(child)
    if issue["state"] != "OPEN":
        return False, f"#{child} is not open (state {issue['state']})"
    labels = {label["name"] for label in issue.get("labels", [])}
    if "sdd:task" not in labels:
        return False, f"#{child} has no sdd:task label"
    if _git(repo, "status", "--porcelain"):
        return False, "the working tree is not clean; commit or remove every change, then run the gate"
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    if not marker_file(repo, tree).is_file():
        return False, f"no gate marker matches HEAD^{{tree}} {tree}; run the build gate (scripts/check.sh)"
    try:
        security_commands = _config.load_security_commands(repo)
    except Exception:
        return False, "could not read security_commands from .claude/sdd-flow.local.md; fix the config file"
    if security_commands and not _security_runner.marker_path(repo, tree).is_file():
        return False, (
            f"security_commands is configured but no security marker matches HEAD^{{tree}} "
            f"{tree}; run scripts/run_security_commands.py"
        )
    if EXEMPT not in labels:
        ok, message = _red_green.verify(child, repo=repo, base=base)
        if not ok:
            return False, message
    run_gh(["issue", "close", str(child), "--reason", "completed"])
    state = _view(child)["state"]
    if state != "CLOSED":
        return False, f"#{child} close did not land: state is {state}"
    return True, f"#{child} closed (gate marker on {tree[:12]})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parent", type=int)
    parser.add_argument("child", type=int)
    parser.add_argument("--base", default="main")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    ok, message = close(args.parent, args.child, repo=args.repo, base=args.base)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
