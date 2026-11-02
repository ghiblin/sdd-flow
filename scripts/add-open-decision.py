#!/usr/bin/env python3
"""Add an unchecked question to an SDD main issue's `## Open decisions` block.

Usage:
  add-open-decision.py <issue-number> --question "<one-line question>"

The `- [ ] _none_` placeholder is replaced; otherwise the line is appended after
the block's last checklist line. No write happens when the same question is
already in the block (up to the next heading or `<!-- sdd:end -->`), open or resolved (`- [x]`/`- [X] <question>`, optionally followed
by ` → <resolution>`), matched exactly, ignoring trailing whitespace. The
`_none_` placeholder (in any spacing) is replaced; `_none_` itself and questions
containing `→` are refused. Blank lines
after the heading are kept and CRLF bodies are read as LF. Only that block changes (UTF-8, never an empty body); the issue
is re-read and the script exits non-zero if the body does not match.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from open_decisions import (  # noqa: E402
    is_placeholder, join_body, new_question_text, normalize, split_block, split_body, state_of,
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


def add_open_decision(number: int, question: str) -> None:
    question = new_question_text(question)
    n = str(number)

    body = read_body(n)
    if state_of(split_block(n, body)[1], question)[0] is not None:
        return
    head, lead, items, tail = split_body(n, body)
    items = [i for i in items if not is_placeholder(i)] + [f"- [ ] {question}"]
    new_body = join_body(head, lead, items, tail)
    run_gh(["issue", "edit", n, "--body-file", "-"], stdin=new_body)

    if read_body(n).strip() != new_body.strip():
        raise SystemExit(f"issue #{n}: body read back does not match what was written")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int)
    parser.add_argument("--question", required=True)
    args = parser.parse_args(argv)
    add_open_decision(args.number, args.question)


if __name__ == "__main__":
    main()
