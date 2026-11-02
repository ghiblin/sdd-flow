#!/usr/bin/env python3
"""Close an `sdd:task` sub-issue once its tree is clean and red came before green.

Usage:
  close-sub-issue.py <main-issue-number> <child> [--base main] [--repo .]

This is the only way to close a sub-issue. It refuses (exit 1, reason on stderr) unless:
`<child>` is an open `sdd:task` sub-issue of `<main>`; the working tree is clean (no tracked
change and no untracked, unignored file); and, unless the sub-issue carries `sdd:no-red-green`,
`verify_red_green.py` finds a non-empty `test:` commit before a `feat:`/`fix:` commit for
`(#<child>)` in `<base>...HEAD`. Then it runs `gh issue close <child> --reason completed` and
re-reads the sub-issue, failing if its state is not CLOSED. Stdlib only; importable (`close`, `main`).

This script does not itself check that the project's build gate passed — the calling skill
instructs running it first, as a plain step. There is no gate-marker file and no hook enforcing
it; a stale or skipped gate is caught by code review, not by a program refusing to proceed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXEMPT = "sdd:no-red-green"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lister = _load("list_sub_issues", "list-sub-issues.py")
_red_green = _load("verify_red_green", "verify_red_green.py")
run_gh = _lister.run_gh


def sub_issues(parent: int) -> list[dict]:
    return _lister.list_sub_issues(parent)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


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
        return False, "the working tree is not clean; commit or remove every change, then run the build gate"
    if EXEMPT not in labels:
        ok, message = _red_green.verify(child, repo=repo, base=base)
        if not ok:
            return False, message
    run_gh(["issue", "close", str(child), "--reason", "completed"])
    state = _view(child)["state"]
    if state != "CLOSED":
        return False, f"#{child} close did not land: state is {state}"
    return True, f"#{child} closed"


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
