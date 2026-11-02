#!/usr/bin/env python3
"""Create an `sdd:task` sub-issue, nest it under the main issue, print its number.

Usage:
  create-sub-issue.py <main-issue-number> --title "<increment description>" [--scenario "<name>" ...] [--needs-spec] [--no-red-green]

The body comes from templates/sub-issue.md (`Part of #<main>`). Each `--scenario`
names one drafted `@wip` scenario the sub-issue implements; they are listed under
a `Scenarios:` line after the template text. `--needs-spec` also adds the
`sdd:needs-spec` label (work the spec section does not describe yet) and verifies
it on read-back. `--no-red-green` adds the `sdd:no-red-green` label (the user
exempted the sub-issue from the red-green check): before it creates anything, the
script reads the main issue and refuses unless a checked `## Open decisions` line
names the title; the label is verified on read-back. Nesting uses the
GraphQL `addSubIssue` mutation; the main issue's sub-issues are then re-read and
the script exits non-zero if the child is missing. When nesting fails the child
still exists: the error names it so it can be reported rather than dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import string
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from open_decisions import require_checked_title  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "sub-issue.md"
LABEL = "sdd:task"
NEEDS_SPEC = "sdd:needs-spec"
NO_RED_GREEN = "sdd:no-red-green"
ADD_SUB_ISSUE = (
    "mutation($p:ID!,$c:ID!){ addSubIssue(input:{issueId:$p, subIssueId:$c})"
    "{ issue{ number } } }"
)
PARENT = "query($id:ID!){ node(id:$id){ ... on Issue { parent { number } } } }"


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


def node_id(number: str) -> str:
    return json.loads(run_gh(["issue", "view", number, "--json", "id"]))["id"]


def code_span(text: str) -> str:
    """`text` as a Markdown code span, so `@name` and `#123` in it neither notify nor link."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if longest else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def create_sub_issue(
    parent: int,
    title: str,
    scenarios: list[str] | None = None,
    needs_spec: bool = False,
    no_red_green: bool = False,
) -> int:
    if not title.strip():
        raise SystemExit("refusing to create a sub-issue without a title")
    scenarios = scenarios or []
    if any(not s.strip() for s in scenarios):
        raise SystemExit("refusing to create a sub-issue with a blank scenario name")
    p = str(parent)
    if no_red_green:
        main_body = json.loads(run_gh(["issue", "view", p, "--json", "body"]))["body"]
        require_checked_title(p, main_body, title)

    body = string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(parent=p)
    if scenarios:
        listed = "\n".join(f"- {code_span(s.strip())}" for s in scenarios)
        body = f"{body.rstrip()}\n\nScenarios:\n{listed}\n"
    extra = ([NEEDS_SPEC] if needs_spec else []) + ([NO_RED_GREEN] if no_red_green else [])
    labels = ["--label", LABEL]
    for name in extra:
        labels += ["--label", name]
    url = run_gh(
        ["issue", "create", "--title", title, *labels, "--body-file", "-"],
        stdin=body,
    )
    match = re.search(r"/issues/(\d+)\s*$", url)
    if not match:
        raise SystemExit(
            f"a sub-issue was created but its number could not be read from gh output {url!r}: "
            "find, nest and report that sub-issue instead of creating another"
        )
    child = match.group(1)

    try:
        parent_id = node_id(p)
        child_id = node_id(child)
        run_gh(["api", "graphql", "-f", f"query={ADD_SUB_ISSUE}", "-f", f"p={parent_id}", "-f", f"c={child_id}"])
        data = json.loads(
            run_gh(["api", "graphql", "-f", f"query={PARENT}", "-f", f"id={child_id}"])
        )
    except SystemExit as err:
        raise SystemExit(
            f"sub-issue #{child} was created but not nested under #{p} ({err.code}): "
            "report the un-nested child"
        )
    parent_of_child = data["data"]["node"]["parent"]
    if not parent_of_child or parent_of_child["number"] != parent:
        raise SystemExit(
            f"sub-issue #{child} was created but is not nested under #{p}: "
            "report the un-nested child"
        )
    if extra:
        names = [
            label["name"]
            for label in json.loads(run_gh(["issue", "view", child, "--json", "labels"]))["labels"]
        ]
        missing = [name for name in extra if name not in names]
        if missing:
            raise SystemExit(
                f"sub-issue #{child} was created and nested under #{p} but does not carry "
                f"{', '.join(missing)}: add the label to #{child}, the sub-issue this run "
                "created, instead of creating another"
            )
    return int(child)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parent", type=int)
    parser.add_argument("--title", required=True)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--needs-spec", action="store_true")
    parser.add_argument("--no-red-green", action="store_true")
    args = parser.parse_args(argv)
    print(
        create_sub_issue(
            args.parent, args.title, args.scenario, args.needs_spec, args.no_red_green
        )
    )


if __name__ == "__main__":
    main()
