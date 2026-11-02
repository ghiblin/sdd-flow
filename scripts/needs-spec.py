#!/usr/bin/env python3
"""List or clear the open `sdd:needs-spec` sub-issues of an SDD main issue.

Usage:
  needs-spec.py <main-issue-number> [--titles]
  needs-spec.py <main-issue-number> --clear <child> [--scenario "<name>" ...] [--no-red-green]

Without `--clear`: prints the number of each open sub-issue that carries the
`sdd:needs-spec` label (work the spec section does not describe yet), one per
line (`number<TAB>title` with `--titles`). Every page of sub-issues is read.
No output means none.

With `--clear`: the child must be an open sub-issue of the main issue. Removes the
`sdd:needs-spec` label if the child still carries it, so a re-run after a failed
read-back and a scoped "Request changes" repeat both work. The list under the
child's `Scenarios:` line becomes exactly the `--scenario` names (Markdown code
spans, so `@name` and `#123` neither notify nor link), without duplicates; with
no `--scenario`, the `Scenarios:` line and its list are removed. Blank lines in
the list and trailing spaces after `Scenarios:` are tolerated; the list ends at
the first line that is neither blank nor a `- ` code-span item. Then it re-reads
the child and exits non-zero unless the label is gone and the list is exactly
those names. `--no-red-green` also adds the `sdd:no-red-green` label (the user
exempted the sub-issue from the red-green check) if the child lacks it: before any
edit, the script reads the main issue and refuses unless a checked
`## Open decisions` line names the child's title; the read-back then also needs
the label on.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from open_decisions import require_checked_title  # noqa: E402

LABEL = "sdd:needs-spec"
NO_RED_GREEN = "sdd:no-red-green"
SUB_ISSUES = (
    "query($id:ID!,$after:String){ node(id:$id){ ... on Issue {"
    " subIssues(first:100, after:$after){ nodes { number title state labels(first:100){ nodes { name } } }"
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


def code_span(text: str) -> str:
    """`text` as a Markdown code span, so `@name` and `#123` in it neither notify nor link."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if longest else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def open_sub_issues(parent: int, titles: dict[int, str] | None = None) -> dict[int, set[str]]:
    """Each open sub-issue of `parent`, in order, with its label names; fills `titles` if given."""
    parent_id = json.loads(run_gh(["issue", "view", str(parent), "--json", "id"]))["id"]
    found: dict[int, set[str]] = {}
    after: str | None = None
    while True:
        args = ["api", "graphql", "-f", f"query={SUB_ISSUES}", "-f", f"id={parent_id}"]
        if after:
            args += ["-f", f"after={after}"]
        page = json.loads(run_gh(args))["data"]["node"]["subIssues"]
        for node in page["nodes"]:
            if node["state"] == "OPEN":
                found[node["number"]] = {label["name"] for label in node["labels"]["nodes"]}
                if titles is not None:
                    titles[node["number"]] = node.get("title", "")
        if not page["pageInfo"]["hasNextPage"]:
            return found
        after = page["pageInfo"]["endCursor"]


def needs_spec(parent: int, titles: dict[int, str] | None = None) -> list[int]:
    return [n for n, names in open_sub_issues(parent, titles).items() if LABEL in names]


def _scenario_block(lines: list[str]) -> tuple[int, int] | None:
    """`(heading, last)` line indexes of the `Scenarios:` list, or None if there is none."""
    heading = next((i for i, line in enumerate(lines) if line.strip() == "Scenarios:"), None)
    if heading is None:
        return None
    last = heading
    for i in range(heading + 1, len(lines)):
        if lines[i].startswith("- `"):
            last = i
        elif lines[i].strip():
            break
    return heading, last


def scenario_list(body: str) -> list[str]:
    """The `- `-code-span items of `body`'s `Scenarios:` list, in order."""
    lines = body.replace("\r\n", "\n").split("\n")
    block = _scenario_block(lines)
    if block is None:
        return []
    heading, last = block
    return [line for line in lines[heading + 1 : last + 1] if line.startswith("- `")]


def _has_heading(body: str) -> bool:
    return _scenario_block(body.replace("\r\n", "\n").split("\n")) is not None


def with_scenarios(body: str, items: list[str]) -> str:
    """`body` with its `Scenarios:` list replaced by `items` (no duplicates); removed if empty."""
    lines = body.replace("\r\n", "\n").rstrip("\n").split("\n")
    new = list(dict.fromkeys(items))
    block = _scenario_block(lines)
    if block is None:
        if not new:
            return "\n".join(lines) + "\n"
        return "\n".join(lines) + "\n\nScenarios:\n" + "\n".join(new) + "\n"
    heading, last = block
    if new:
        lines = lines[:heading] + ["Scenarios:"] + new + lines[last + 1 :]
    else:
        before = lines[:heading]
        while before and not before[-1].strip():
            before.pop()
        after = lines[last + 1 :]
        while after and not after[0].strip():
            after.pop(0)
        lines = before + ([""] + after if before and after else after)
    return "\n".join(lines).rstrip("\n") + "\n"


def view(child: int) -> tuple[str, list[str]]:
    data = json.loads(run_gh(["issue", "view", str(child), "--json", "body,labels"]))
    return data["body"], [label["name"] for label in data["labels"]]


def clear(parent: int, child: int, scenarios: list[str], no_red_green: bool = False) -> None:
    if any(not s.strip() for s in scenarios):
        raise SystemExit("refusing to record a blank scenario name")
    titles: dict[int, str] = {}
    subs = open_sub_issues(parent, titles)
    if child not in subs:
        raise SystemExit(f"#{child} is not an open sub-issue of #{parent}")
    if no_red_green:
        main_body = json.loads(run_gh(["issue", "view", str(parent), "--json", "body"]))["body"]
        require_checked_title(str(parent), main_body, titles[child])
    items = list(dict.fromkeys(f"- {code_span(s.strip())}" for s in scenarios))
    args = ["issue", "edit", str(child)]
    needs_edit = False
    if LABEL in subs[child]:
        args += ["--remove-label", LABEL]
        needs_edit = True
    if no_red_green and NO_RED_GREEN not in subs[child]:
        args += ["--add-label", NO_RED_GREEN]
        needs_edit = True
    current = view(child)[0]
    body = None
    if scenario_list(current) != items or (not items and _has_heading(current)):
        body = with_scenarios(current, items)
        args += ["--body-file", "-"]
        needs_edit = True
    if needs_edit:
        run_gh(args, stdin=body)

    after_body, labels = view(child)
    stale_heading = not items and _has_heading(after_body)
    missing_exemption = no_red_green and NO_RED_GREEN not in labels
    if LABEL in labels or scenario_list(after_body) != items or stale_heading or missing_exemption:
        raise SystemExit(f"the edit of #{child} did not land: run the same clear for #{child} again")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parent", type=int)
    parser.add_argument("--clear", type=int, metavar="CHILD")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--titles", action="store_true")
    parser.add_argument("--no-red-green", action="store_true")
    args = parser.parse_args(argv)
    if args.clear is None:
        if args.scenario:
            parser.error("--scenario needs --clear")
        if args.no_red_green:
            parser.error("--no-red-green needs --clear")
        titles: dict[int, str] = {}
        for number in needs_spec(args.parent, titles):
            print(f"{number}\t{titles[number]}" if args.titles else number)
        return
    if args.titles:
        parser.error("--titles lists; it does not go with --clear")
    clear(args.parent, args.clear, args.scenario, args.no_red_green)


if __name__ == "__main__":
    main()
