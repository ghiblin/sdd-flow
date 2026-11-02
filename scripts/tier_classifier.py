#!/usr/bin/env python3
"""Propose a tier (0 mechanical, 1 bugfix, 2 feature) for an intent, from a short description.

Usage (library, called by the sdd-flow-intent skill):
  from tier_classifier import classify
  tier, rationale, question = classify(intent_text, build_gate_green_before=True)

Usage (CLI):
  python3 tier_classifier.py "<intent text>" [--build-gate-green-before=true|false]

This is a heuristic proposal, never a decision: `sdd-flow-intent` always surfaces it to
the user as a `NEEDS_INPUT` (`tiers.classification: auto`, the default) or always asks
(`always-ask`) — see sdd_flow_config.py. Getting the default guess right matters far more
than getting it exactly right, because a wrong guess costs one extra question, not a wrong
pipeline silently run.
"""
from __future__ import annotations

import argparse
import re
import sys

# Verbs that describe moving/renaming/splitting code with no claimed behavior change.
MECHANICAL_VERBS = re.compile(
    r"\b(split|rename|move|extract|reformat|re-?format|dedupe|deduplicate|"
    r"refactor|reorganize|restructure|bump|upgrade|downgrade|tidy|cleanup|clean up)\b",
    re.IGNORECASE,
)
# Phrases that explicitly disclaim or claim a behavior change either way.
NO_BEHAVIOR_CHANGE = re.compile(r"\bno (behaviou?r|functional) change\b", re.IGNORECASE)
BEHAVIOR_CHANGE_CLAIMED = re.compile(
    r"\b(fix|bug|crash|error|wrong|incorrect|broken|regression|add|implement|support|feature)\b",
    re.IGNORECASE,
)
BUGFIX_VERBS = re.compile(
    r"\b(fix|bug|crash(?:es|ing)?|error|wrong|incorrect|broken|regression)\b", re.IGNORECASE
)
AMBIGUITY_MARKERS = re.compile(
    r"\b(design|decide|should we|not sure|explore|investigate|new feature|"
    r"from scratch|architecture|approach)\b",
    re.IGNORECASE,
)


def classify(intent_text: str, build_gate_green_before: bool = True) -> tuple[int, str, str]:
    """Return (proposed tier, one-line rationale, the NEEDS_INPUT question text)."""
    text = intent_text.strip()
    mechanical = bool(MECHANICAL_VERBS.search(text))
    disclaims_behavior_change = bool(NO_BEHAVIOR_CHANGE.search(text))
    claims_behavior_change = bool(BEHAVIOR_CHANGE_CLAIMED.search(text))
    is_bugfix = bool(BUGFIX_VERBS.search(text))
    is_ambiguous = bool(AMBIGUITY_MARKERS.search(text))

    if mechanical and build_gate_green_before and (disclaims_behavior_change or not claims_behavior_change) and not is_ambiguous:
        tier = 0
        rationale = (
            "reads as a mechanical change (refactor/split/rename/move/dependency-bump "
            "wording, no claimed behavior change, build gate already green)"
        )
    elif is_bugfix and not is_ambiguous:
        tier = 1
        rationale = "reads as a bugfix: a known, narrow defect with no open design question"
    else:
        tier = 2
        rationale = "reads as a feature or carries a judgment call the heuristic can't resolve on its own"

    question = (
        f"I read this intent as Tier {tier} ({rationale}). Classify it as:\n"
        "- Tier 0 — mechanical (no spec, no review roles, one batch, one PR)\n"
        "- Tier 1 — bugfix (one reviewer role, red→green→optional refactor)\n"
        "- Tier 2 — feature (full spec review, red→green→optional refactor per sub-issue)\n"
        "Confirm the proposed tier, or pick a different one."
    )
    return tier, rationale, question


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("intent_text")
    parser.add_argument("--build-gate-green-before", default="true", choices=["true", "false"])
    args = parser.parse_args(argv)
    tier, rationale, question = classify(args.intent_text, args.build_gate_green_before == "true")
    print(f"tier: {tier}")
    print(f"rationale: {rationale}")
    print(question)
    return 0


if __name__ == "__main__":
    sys.exit(main())
