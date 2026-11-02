#!/usr/bin/env python3
"""Write or check the build-gate marker for the current clean tree.

`scripts/check.sh` reads the clean tree before it runs the gate and writes a
marker after the gate passes. The marker is the file
`$(git rev-parse --git-path sdd-gate/<tree>)`, where `<tree>` is
`git rev-parse HEAD^{tree}`. It sits in the worktree's own git dir, so it is
never committed and each worktree keeps its own markers. A marker is valid only
while the working tree is clean (no tracked change and no untracked, unignored
file) and `HEAD^{tree}` still matches it.

Usage:
    scripts/gate_marker.py [--repo DIR] clean-tree   # print HEAD^{tree} if clean, else nothing
    scripts/gate_marker.py [--repo DIR] write TREE   # write the marker if still clean on TREE
    scripts/gate_marker.py [--repo DIR] check        # exit 0 only if a marker matches the clean tree
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER_DIR = "sdd-gate"


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


def write(repo: Path, tree: str | None) -> bool:
    """Write the marker for `tree` if the tree is still clean on it."""
    if not tree or tree_if_clean(repo) != tree:
        return False
    path = marker_path(repo, tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = _git(repo, "rev-parse", "HEAD")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(f"{head} {stamp}\n", encoding="utf-8")
    return True


def check(repo: Path) -> bool:
    """True only if the tree is clean and a marker matches HEAD^{tree}."""
    tree = tree_if_clean(repo)
    return tree is not None and marker_path(repo, tree).is_file()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("clean-tree")
    write_parser = sub.add_parser("write")
    write_parser.add_argument("tree", nargs="?", default="")
    sub.add_parser("check")
    args = parser.parse_args(argv)

    if args.command == "clean-tree":
        print(tree_if_clean(args.repo) or "")
        return 0
    if args.command == "write":
        if write(args.repo, args.tree):
            print(f"gate marker written for tree {args.tree}")
        else:
            print(
                "gate passed, but the tree was not clean (or changed) during the run; "
                "no gate marker written",
                file=sys.stderr,
            )
        return 0
    if check(args.repo):
        return 0
    print("no gate marker matches the clean HEAD^{tree}; run scripts/check.sh", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
