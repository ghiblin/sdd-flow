#!/usr/bin/env python3
"""Create an ADR from templates/adr.md under docs/adr/, update its README index, and print its path.

Usage:
  create-adr.py --title "<title>" --context "<context>" --decision "<decision>" \
      --consequences "<consequences>" [--status "<status>"] [--repo <path>]

Numbers the file `ADR-NNN-<slug>.md` (3-digit, one above the highest `ADR-NNN-*.md`
already in `docs/adr/`, or 001 if none exist) and appends a row to
`docs/adr/README.md` (created with its header if absent). Re-reads both files after
writing and exits non-zero if either does not contain what was just written — any
failure after the ADR file exists names its path, so it is fixed rather than
duplicated. Title, context, decision and consequences must each be a single line.
"""
from __future__ import annotations

import argparse
import re
import string
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "adr.md"
NUMBER_RE = re.compile(r"^ADR-(\d{3})-")
README_HEADER = "# Architecture Decision Records\n\n| ADR | Title | Status |\n|-----|-------|--------|\n"


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise SystemExit(f"title {title!r} has no word characters to slugify")
    return slug


def next_number(adr_dir: Path) -> int:
    highest = 0
    if adr_dir.is_dir():
        for path in adr_dir.glob("ADR-*.md"):
            match = NUMBER_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def render_adr(number: int, title: str, status: str, context: str, decision: str, consequences: str) -> str:
    return string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        number=f"{number:03d}",
        title=title,
        status=status,
        context=context,
        decision=decision,
        consequences=consequences,
    )


def render_readme_row(number: int, slug: str, title: str, status: str) -> str:
    return f"| [ADR-{number:03d}](ADR-{number:03d}-{slug}.md) | {title} | {status} |\n"


def update_readme(readme_path: Path, row: str) -> None:
    text = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else README_HEADER
    if not text.endswith("\n"):
        text += "\n"
    readme_path.write_text(text + row, encoding="utf-8")


def create_adr(
    title: str,
    context: str,
    decision: str,
    consequences: str,
    status: str = "Accepted",
    repo: Path | str = ".",
) -> Path:
    for name, text in [
        ("title", title), ("context", context), ("decision", decision),
        ("consequences", consequences), ("status", status),
    ]:
        if not text.strip():
            raise SystemExit(f"refusing to create an ADR without a non-empty {name}")
    for name, text in [("title", title), ("status", status)]:
        if "\n" in text.strip():
            raise SystemExit(f"{name} must be a single line: {text!r}")

    adr_dir = Path(repo) / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    number = next_number(adr_dir)
    slug = slugify(title)
    adr_path = adr_dir / f"ADR-{number:03d}-{slug}.md"
    if adr_path.exists():
        raise SystemExit(f"{adr_path} already exists: find and fix that ADR instead of creating another")

    body = render_adr(number, title, status, context, decision, consequences)
    adr_path.write_text(body, encoding="utf-8")

    row = render_readme_row(number, slug, title, status)
    readme_path = adr_dir / "README.md"
    update_readme(readme_path, row)

    if adr_path.read_text(encoding="utf-8") != body:
        raise SystemExit(f"{adr_path}: content read back does not match what was written")
    if row not in readme_path.read_text(encoding="utf-8"):
        raise SystemExit(f"{readme_path}: new row was not found after writing ({adr_path} was created)")
    return adr_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--consequences", required=True)
    parser.add_argument("--status", default="Accepted")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    path = create_adr(
        args.title, args.context, args.decision, args.consequences, args.status, args.repo
    )
    print(path.as_posix())


if __name__ == "__main__":
    main()
