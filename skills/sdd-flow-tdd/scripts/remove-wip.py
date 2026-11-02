#!/usr/bin/env python3
"""Remove only the @wip tag of the named scenarios in one Gherkin feature file.

The tag goes from each named scenario's own tag lines and from the tag lines of
its Examples blocks. Every other tag stays, a tag line is deleted only when @wip
was its only tag, and nothing else in the file changes (line endings included).
Blank and comment lines may stand between a tag line and its header.

The script exits non-zero and changes nothing when a name matches no scenario or
more than one, when a named scenario has no @wip tag, or when the @wip tag is on
the Feature or on a Rule above a named scenario, or when the file is not UTF-8.

Usage:
    remove-wip.py <feature file> --scenario "<name>" [--scenario "<name>" ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WIP = re.compile(r"(?<!\S)@wip(?!\S)")
HEADER = re.compile(
    r"^\s*(Feature|Rule|Background|Scenario Outline|Scenario Template|Scenario|Example"
    r"|Examples|Scenarios):\s*(.*?)\s*$"
)
SCENARIO_KEYWORDS = {"Scenario", "Scenario Outline", "Scenario Template", "Example"}
EXAMPLES_KEYWORDS = {"Examples", "Scenarios"}


class Scenario:
    """A scenario header with the tag lines that apply to it."""

    def __init__(self, name: str, rule_tag_lines: list[int], tag_lines: list[int]):
        self.name = name
        self.rule_tag_lines = rule_tag_lines
        self.tag_lines = tag_lines


def is_tag_line(line: str) -> bool:
    return line.lstrip().startswith("@")


def tags_above(lines: list[str], index: int) -> list[int]:
    """The tag lines above a header, over interleaved comment and blank lines."""
    found = []
    i = index - 1
    while i >= 0:
        stripped = lines[i].strip()
        if is_tag_line(lines[i]):
            found.append(i)
        elif stripped and not stripped.startswith("#"):
            break
        i -= 1
    return found


def parse(lines: list[str]) -> tuple[list[int], list[Scenario]]:
    feature_tags: list[int] = []
    rule_tags: list[int] = []
    scenarios: list[Scenario] = []
    current: Scenario | None = None
    fence: str | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith('"""') or stripped.startswith("```"):
            fence = stripped[:3]
            continue
        match = HEADER.match(line.rstrip("\r\n"))
        if not match:
            continue
        keyword, name = match.group(1), match.group(2)
        if keyword == "Feature":
            feature_tags = tags_above(lines, i)
            rule_tags = []
            current = None
        elif keyword == "Rule":
            rule_tags = tags_above(lines, i)
            current = None
        elif keyword == "Background":
            current = None
        elif keyword in SCENARIO_KEYWORDS:
            current = Scenario(name, rule_tags, tags_above(lines, i))
            scenarios.append(current)
        elif keyword in EXAMPLES_KEYWORDS and current is not None:
            current.tag_lines += tags_above(lines, i)
    return feature_tags, scenarios


def strip_wip(line: str) -> str | None:
    """The tag line without @wip, or None when @wip was its only content."""
    body = line.rstrip("\r\n")
    ending = line[len(body):]
    body = re.sub(r"(?<!\S)@wip(?!\S)[ \t]*", "", body).rstrip()
    if not body.strip():
        return None
    return body + ending


def remove_wip(text: str, names: list[str]) -> str:
    """The text with the @wip tag of each named scenario removed; ValueError on refusal."""
    lines = text.splitlines(keepends=True)
    feature_tags, scenarios = parse(lines)
    if any(WIP.search(lines[i]) for i in feature_tags):
        raise ValueError("the @wip tag is on the Feature, not on a scenario")
    edits: set[int] = set()
    for name in dict.fromkeys(names):
        matches = [s for s in scenarios if s.name == name]
        if not matches:
            raise ValueError(f"no scenario is named {name!r}")
        if len(matches) > 1:
            raise ValueError(f"more than one scenario is named {name!r}")
        scenario = matches[0]
        if any(WIP.search(lines[i]) for i in scenario.rule_tag_lines):
            raise ValueError(f"the @wip tag is on the Rule above scenario {name!r}")
        wip_lines = [i for i in scenario.tag_lines if WIP.search(lines[i])]
        if not wip_lines:
            raise ValueError(f"scenario {name!r} has no @wip tag")
        edits.update(wip_lines)
    out = []
    for i, line in enumerate(lines):
        if i in edits:
            line = strip_wip(line)
            if line is None:
                continue
        out.append(line)
    return "".join(out)



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("feature", type=Path)
    parser.add_argument("--scenario", action="append", required=True, metavar="NAME")
    args = parser.parse_args(argv)
    try:
        text = args.feature.read_bytes().decode("utf-8")
    except OSError as err:
        print(f"remove-wip: cannot read {args.feature}: {err}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as err:
        print(f"remove-wip: {args.feature}: the file is not UTF-8 ({err}); nothing changed", file=sys.stderr)
        return 1
    try:
        new = remove_wip(text, args.scenario)
    except ValueError as err:
        print(f"remove-wip: {args.feature}: {err}; nothing changed", file=sys.stderr)
        return 1
    args.feature.write_bytes(new.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
