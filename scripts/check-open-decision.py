#!/usr/bin/env python3
"""Check off a question in an SDD main issue's `## Open decisions` block.

Usage:
  check-open-decision.py <issue-number> --question "<open question>" [--resolved-as "<decision (who, date)>"]

Turns `- [ ] <question>` (inside the block) into `- [x] <question>`, or into
`- [x] <question> → <decision>` with `--resolved-as`, so the line keeps its
question. No write happens when the question is already checked (`- [x]` or
`- [X]`, whatever its resolution). A question that is not in the block exits
non-zero, and so does `_none_`. The block runs up to the next heading or
`<!-- sdd:end -->`, so a line after a blank or prose line still counts. An open copy of the question wins over a
checked one. Lines match exactly (never by prefix), ignoring trailing whitespace
and box spacing. Existing open questions containing `→` can still be checked
off; their resolved line writes that `→` as `->`. Blank
lines after the heading are kept and CRLF bodies are read as LF. Only that line
changes (UTF-8, never an empty body); the issue is re-read and the script exits
non-zero if the body does not match.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from open_decisions import (  # noqa: E402
    normalize, question_text, resolved, single_line, split_block, state_of,
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


def read_body(number: str) -> str:
    return normalize(json.loads(run_gh(["issue", "view", number, "--json", "body"]))["body"])


def check_open_decision(number: int, question: str, resolved_as: str | None = None) -> None:
    question = question_text(question)
    resolution = None if resolved_as is None else single_line(resolved_as, "resolution")
    n = str(number)

    head, block, rest = split_block(n, read_body(n))
    state, index = state_of(block, question)
    if state == "checked":
        return
    if state is None:
        raise SystemExit(f"issue #{n}: no open decision '{question}' in the '## Open decisions' block")

    block[index] = resolved(question, resolution)
    new_body = head + "\n".join(block + rest)
    run_gh(["issue", "edit", n, "--body-file", "-"], stdin=new_body)

    if read_body(n).strip() != new_body.strip():
        raise SystemExit(f"issue #{n}: body read back does not match what was written")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int)
    parser.add_argument("--question", required=True)
    parser.add_argument("--resolved-as")
    args = parser.parse_args(argv)
    check_open_decision(args.number, args.question, args.resolved_as)


if __name__ == "__main__":
    main()
