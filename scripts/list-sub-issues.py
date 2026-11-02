#!/usr/bin/env python3
"""List an SDD main issue's sub-issues, one `number<TAB>STATE<TAB>title` line each.

Usage:
  list-sub-issues.py <main-issue-number> [--open]

`--open` keeps only the OPEN ones. Every page of sub-issues is read. No output means no (matching) sub-issues.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

SUB_ISSUES = (
    "query($id:ID!,$after:String){ node(id:$id){ ... on Issue {"
    " subIssues(first:100, after:$after){ nodes { number title state }"
    " pageInfo { hasNextPage endCursor } } } } }"
)


def run_gh(args: list[str], stdin: str | None = None) -> str:
    """Run `gh` with UTF-8 stdin/stdout; exit non-zero on failure."""
    result = subprocess.run(
        ["gh", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"gh {' '.join(args[:2])} failed ({result.returncode})")
    return result.stdout.strip()


def list_sub_issues(parent: int, open_only: bool = False) -> list[dict]:
    p = str(parent)
    parent_id = json.loads(run_gh(["issue", "view", p, "--json", "id"]))["id"]
    nodes: list[dict] = []
    after: str | None = None
    while True:
        args = ["api", "graphql", "-f", f"query={SUB_ISSUES}", "-f", f"id={parent_id}"]
        if after:
            args += ["-f", f"after={after}"]
        page = json.loads(run_gh(args))["data"]["node"]["subIssues"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return [n for n in nodes if n["state"] == "OPEN"] if open_only else nodes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parent", type=int)
    parser.add_argument("--open", action="store_true", dest="open_only")
    args = parser.parse_args(argv)
    for node in list_sub_issues(args.parent, args.open_only):
        print(f"{node['number']}\t{node['state']}\t{node['title']}")


if __name__ == "__main__":
    main()
