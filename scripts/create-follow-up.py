#!/usr/bin/env python3
"""File one reviewer follow-up finding as a plain `sdd:follow-up` issue, print its number.

Usage:
  create-follow-up.py <main-issue-number> --title "<title>" --finding "<text>"

The body starts with `Follow-up from #<main>`, then gives the finding text in a
fenced block, so an `@name` or `#123` in it neither notifies nor links. The issue
is not a sub-issue, so it never blocks the main issue's `complete` stage. The
script first makes sure the `sdd:follow-up` label exists: it reads the repo's
labels and runs `gh label create` only when the label is missing, so a repo that
adopted SDD before the label was added still works, and an existing label is
never changed. A failed create is fine when the label exists after it (another
run created it).
It re-reads the new issue and exits non-zero unless the `sdd:follow-up` label
and the first body line landed; the error names the new issue so it can be fixed
rather than filed again.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

LABEL = "sdd:follow-up"
LABEL_COLOR = "BFD4F2"
LABEL_DESCRIPTION = "SDD: reviewer finding deferred to a later issue"


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


def fenced(text: str) -> str:
    """`text` in a fenced block whose fence is longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def has_label() -> bool:
    names = json.loads(run_gh(["label", "list", "--search", LABEL, "--limit", "1000", "--json", "name"]) or "[]")
    return any(item.get("name") == LABEL for item in names)


def ensure_label() -> None:
    """Create the `sdd:follow-up` label only when the repo does not have it yet.

    When the create fails, the labels are read again: a label that another run
    created in the meantime counts as success.
    """
    if has_label():
        return
    try:
        run_gh(["label", "create", LABEL, "--color", LABEL_COLOR, "--description", LABEL_DESCRIPTION])
    except SystemExit as create_error:
        try:
            exists = has_label()
        except SystemExit:
            exists = False
        if not exists:
            raise create_error


def create_follow_up(main: int, title: str, finding: str) -> int:
    if not title.strip():
        raise SystemExit("refusing to create a follow-up issue without a title")
    if not finding.strip():
        raise SystemExit("refusing to create a follow-up issue without a finding")
    first_line = f"Follow-up from #{main}"
    body = f"{first_line}\n\n{fenced(finding.strip())}\n"
    ensure_label()
    url = run_gh(
        ["issue", "create", "--title", title.strip(), "--label", LABEL, "--body-file", "-"],
        stdin=body,
    )
    match = re.search(r"/issues/(\d+)\s*$", url)
    if not match:
        raise SystemExit(
            f"a follow-up issue was created but its number could not be read from gh output "
            f"{url!r}: find and report that issue instead of creating another"
        )
    number = match.group(1)

    data = json.loads(run_gh(["issue", "view", number, "--json", "labels,body"]))
    names = [label["name"] for label in data["labels"]]
    lines = (data.get("body") or "").splitlines()
    problems = []
    if LABEL not in names:
        problems.append(f"the {LABEL} label")
    if not lines or lines[0].strip() != first_line:
        problems.append(f"the first body line {first_line!r}")
    if problems:
        raise SystemExit(
            f"follow-up issue #{number} was created but does not carry "
            f"{' and '.join(problems)}: fix #{number}, the issue this run created, "
            "instead of creating another"
        )
    return int(number)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("main", type=int)
    parser.add_argument("--title", required=True)
    parser.add_argument("--finding", required=True)
    args = parser.parse_args(argv)
    print(create_follow_up(args.main, args.title, args.finding))


if __name__ == "__main__":
    main()
