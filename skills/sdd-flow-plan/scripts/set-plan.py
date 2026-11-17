#!/usr/bin/env python3
"""Replace the `## Plan` block of an SDD main issue with new content.

Usage:
  set-plan.py <issue-number> --body-file <path>

The block runs from the `## Plan` heading up to the next heading at `#` or
`##` level, or the `<!-- sdd:end -->` marker — an internal `###`+ subheading
inside the plan's own content does not end the block early. There is no
separate `open_decisions.py`-style module for this because only this script
needs a block boundary one level looser than `## Open decisions`'s (that one
stops at *any* `#`-`######` heading; a Plan needs its own subheadings).

Refuses unless the body has exactly one `## Plan` heading. Rewrites only that
block (UTF-8, never an empty body); re-reads the issue afterward and exits
non-zero if the block does not match what was written. CRLF bodies are read
(and written back) as LF.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PLAN_HEADING = "## Plan\n"
# A line at `#` or `##` level (not `###`+), or the sdd end marker, ends the block.
BOUNDARY_RE = re.compile(r"^(?:#{1,2}(?:[ \t]|$)|<!-- sdd:end)")


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


def read_issue(number: str) -> str:
    issue = json.loads(run_gh(["issue", "view", number, "--json", "body"]))
    # CRLF bodies (saved by the GitHub web UI) are read as LF.
    return issue["body"].replace("\r\n", "\n")


def split_plan(number: str, body: str) -> tuple[str, str, str]:
    """Split a body into (text through the '## Plan' heading, its old content, the rest from the next boundary)."""
    if not body.strip():
        raise SystemExit(f"issue #{number}: refusing to write an empty body — gh issue view likely failed")
    if body.count(PLAN_HEADING) != 1:
        raise SystemExit(f"issue #{number}: expected exactly one '## Plan' heading in the body")
    head, rest = body.split(PLAN_HEADING)
    lines = rest.split("\n")
    end = next((i for i, line in enumerate(lines) if BOUNDARY_RE.match(line)), len(lines))
    return head + PLAN_HEADING, "\n".join(lines[:end]), "\n".join(lines[end:])


def set_plan(number: int, content: str) -> None:
    n = str(number)
    body = read_issue(n)
    head, _, tail = split_plan(n, body)
    content = content.strip("\n")
    new_body = f"{head}{content}\n{tail}" if content else f"{head}{tail}"
    if new_body == body:
        return
    run_gh(["issue", "edit", n, "--body-file", "-"], stdin=new_body)

    body_back = read_issue(n)
    if body_back.strip() != new_body.strip():
        raise SystemExit(f"issue #{n}: body read back does not match what was written")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int)
    parser.add_argument("--body-file", required=True, dest="body_file")
    args = parser.parse_args(argv)
    content = Path(args.body_file).read_text(encoding="utf-8")
    set_plan(args.number, content)


if __name__ == "__main__":
    main()
