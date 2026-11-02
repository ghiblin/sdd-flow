"""Pure helpers for an SDD main issue's `## Open decisions` block (no I/O).

Imported by add-open-decision.py, check-open-decision.py, create-sub-issue.py,
needs-spec.py and set-stage.py. Lookups (`split_block`) read the whole block, up to
the next heading or `<!-- sdd:end -->`; a new question goes after the first run of
checklist lines (`split_body`). A resolved line
keeps its question: `- [x] <question>` or `- [x] <question> → <resolution>`,
with any `→` inside an older question written as `->`.
GitHub's `- [X]` counts as checked, and CRLF bodies are read as LF.
"""
from __future__ import annotations

import re

MARKER = "## Open decisions\n"
SEP = " → "
ITEM_RE = re.compile(r"^- \[([ xX])\]\s*(.*?)\s*$")
# The block ends at the next ATX heading (`#` to `######`, then a space, a tab
# or the line end) or at the sdd block end marker.
BLOCK_END_RE = re.compile(r"^(?:#{1,6}(?:[ \t]|$)|<!-- sdd:end)")


def normalize(body: str) -> str:
    """Read a CRLF body (saved by the GitHub web UI) as LF."""
    return body.replace("\r\n", "\n")


def single_line(text: str, what: str) -> str:
    text = text.strip()
    if not text or "\n" in text:
        raise SystemExit(f"the {what} must be a single non-empty line")
    return text


def question_text(text: str) -> str:
    """Validate a question for checking off: one line, not the placeholder."""
    text = single_line(text, "question")
    if text == "_none_":
        raise SystemExit("'_none_' is the empty-block placeholder, not a question")
    return text


def new_question_text(text: str) -> str:
    """Validate a question for adding: also no arrow, so ` → <resolution>` stays unambiguous."""
    text = question_text(text)
    if SEP.strip() in text:
        raise SystemExit(f"a new question must not contain '{SEP.strip()}' (it separates the resolution)")
    return text


def split_body(number: str, body: str) -> tuple[str, list[str], list[str], list[str]]:
    """Split a body into (text up to the heading, blank lines after it, checklist lines, the rest)."""
    if not body.strip():
        raise SystemExit(f"issue #{number}: refusing to write an empty body — gh issue view likely failed")
    if body.count(MARKER) != 1:
        raise SystemExit(f"issue #{number}: expected exactly one '## Open decisions' block in the body")
    head, rest = body.split(MARKER)
    lines = rest.split("\n")
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start == len(lines) or not lines[start].startswith("- ["):
        start = 0
    end = start
    while end < len(lines) and lines[end].startswith("- ["):
        end += 1
    return head + MARKER, lines[:start], lines[start:end], lines[end:]


def split_block(number: str, body: str) -> tuple[str, list[str], list[str]]:
    """Split a body into (text up to the heading, every line of the block, the rest).

    The block runs up to the next heading or `<!-- sdd:end -->`. Unlike
    `split_body`, it does not stop at the first blank or prose line, so a
    checklist line after a gap (a web-UI edit) is still part of it.
    `head + "\\n".join(block + rest)` gives back the body.
    """
    head, lead, items, tail = split_body(number, body)
    lines = lead + items + tail
    end = next((i for i, line in enumerate(lines) if BLOCK_END_RE.match(line)), len(lines))
    return head, lines[:end], lines[end:]


def join_body(head: str, lead: list[str], items: list[str], tail: list[str]) -> str:
    return head + "\n".join(lead + items + tail)


def parse(line: str) -> tuple[str | None, str]:
    """Return (state, text) for a checklist line: state is 'open', 'checked' or None if malformed.

    Tolerates `[X]`, missing space after the box and trailing whitespace.
    """
    match = ITEM_RE.match(line)
    if not match:
        return None, line
    return ("open" if match.group(1) == " " else "checked"), match.group(2)


def is_placeholder(line: str) -> bool:
    """True for the open `- [ ] _none_` placeholder (in any tolerated spacing)."""
    return parse(line) == ("open", "_none_")


def canonical(question: str) -> str:
    """The question as written on a resolved line: `→` becomes `->`, so ` → ` only ever separates the resolution."""
    return question.replace(SEP.strip(), "->")


def state_of(items: list[str], question: str) -> tuple[str | None, int]:
    """Find the question in the block: ('open'|'checked', index), or (None, -1) when absent.

    An open copy wins over a checked one, so a duplicate open line is never
    hidden by an earlier resolution. An open line matches when its text is
    exactly the question; a checked line matches `<canonical question>`, optionally
    followed by ` → <resolution>` (an empty resolution included). Never a mere prefix.
    """
    parsed = [(i, *parse(line)) for i, line in enumerate(items)]
    parsed = [(i, state, text) for i, state, text in parsed if (state, text) != ("open", "_none_")]
    for index, state, text in parsed:
        if state == "open" and text == question:
            return "open", index
    resolved_as = canonical(question)
    for index, state, text in parsed:
        if state == "checked" and (
            text == question
            or text == resolved_as
            or (text + " ").startswith(resolved_as + SEP)
            # Older resolved lines kept a raw `→` inside the question.
            or (resolved_as != question and (text + " ").startswith(question + SEP))
        ):
            return "checked", index
    return None, -1


def resolved(question: str, resolution: str | None) -> str:
    question = canonical(question)
    return f"- [x] {question}" if resolution is None else f"- [x] {question}{SEP}{resolution}"


APPROVALS = ("yes", "approved", "exempt")


def exemption_question(title: str) -> str:
    """The red-green exemption question for `title`, as a resolved line writes it."""
    return canonical(f"Exempt the sub-issue {title} from the red-green check?")


def approves(resolution: str) -> bool:
    """True when a resolution starts with an approval word: `yes`, `approved` or `exempt`."""
    words = re.findall(r"[a-z]+", resolution.lower())
    return bool(words) and words[0] in APPROVALS


def require_checked_title(number: str, body: str, title: str) -> None:
    """Exit non-zero unless the block has the approved exemption question for `title`.

    The question part of the checked line (before ` → <resolution>`) must be
    exactly `exemption_question(title)`, and the resolution must start with an
    approval word. A line that only mentions the title, a checked line with no
    resolution, and a rejection (`→ no, ...`) are not approvals.
    """
    title = title.strip()
    if not title:
        raise SystemExit("refusing to look up an approval for a blank title")
    question = exemption_question(title)
    _, _, items, _ = split_body(number, normalize(body))
    for line in items:
        state, text = parse(line)
        asked, _, resolution = (text + " ").partition(SEP)
        if state == "checked" and asked.strip() == question and approves(resolution):
            return
    raise SystemExit(
        f"no checked `## Open decisions` line of #{number} approves {question!r} "
        f"(`- [x] {question}{SEP}yes (user, <date>)`): record that question for this "
        "sub-issue and wait for the user to approve it"
    )
