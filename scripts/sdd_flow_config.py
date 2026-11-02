#!/usr/bin/env python3
"""Load and validate the project-local sdd-flow config.

Usage (as a library — every sdd-flow skill/agent that needs a config value imports this):
  from sdd_flow_config import load, tier_profile
  cfg = load(repo)               # defaults applied for every missing key
  profile = tier_profile(cfg, 0) # the Tier 0 profile dict

Usage (CLI, for a skill that only needs one value from a shell step):
  python3 sdd_flow_config.py <repo> get state_backend
  python3 sdd_flow_config.py <repo> get-tier-profile 1

The config file is `.claude/sdd-flow.local.md` in the project root: YAML-ish frontmatter
between two `---` lines, read with `_parse_frontmatter` below (a small, dependency-free
reader — this project takes no third-party packages, so there is no real YAML parser
available; the schema is intentionally shallow enough that this is sufficient). A missing
file is not an error: every key gets its default, so the plugin works with zero
configuration.

Some config values name a strategy that is not implemented yet (for example
`state_backend: local-file`) — tracked as an issue in the sdd-flow repo and guarded by the
IMPLEMENTED registry below. Choosing an unimplemented value is a hard error with the
tracking issue in the message, never a silent fallback to the default.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = ".claude/sdd-flow.local.md"

# Every value a key may take that the plugin actually implements. A key not listed
# here is never checked against this registry (e.g. `worktree.enabled` is a plain bool).
# A key present here whose chosen value is absent from its set is a hard error naming
# the tracking issue, not a silent fallback.
IMPLEMENTED: dict[str, dict[str, str | None]] = {
    "state_backend": {
        "github-issues": None,
        # value -> tracking-issue URL/number, filled in once the issue exists.
        "local-file": "https://github.com/ghiblin/sdd-flow/issues/1",
    },
    "tiers.classification": {
        "auto": None,
        "always-ask": None,
    },
}

DEFAULT_PROFILES: dict[int, dict[str, Any]] = {
    0: {
        "spec_review_roles": [],
        "code_review_rounds": 1,
        "gherkin_required": False,
        "batch_mode": True,
        "refactor_step": False,
    },
    1: {
        "spec_review_roles": ["tech-lead"],
        "code_review_rounds": 1,
        "gherkin_required": False,
        "batch_mode": False,
        "refactor_step": True,
    },
    2: {
        "spec_review_roles": ["pm", "tech-lead", "qa"],
        "code_review_rounds": 2,
        "gherkin_required": True,
        "batch_mode": False,
        "refactor_step": True,
    },
}

DEFAULTS: dict[str, Any] = {
    "state_backend": "github-issues",
    "tiers": {
        "classification": "auto",
        "profiles": DEFAULT_PROFILES,
    },
    "notifications": {
        "desktop": False,
        "push": False,
    },
    "worktree": {
        "enabled": True,
    },
    "rules_file_glob": "*/RULES.md",
}


class ConfigError(Exception):
    """An unimplemented or malformed config value. Always a hard error, never a fallback."""


def _frontmatter_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ConfigError(f"{path}: expected the file to start with a `---` frontmatter line")
    end = text.find("\n---", 3)
    if end == -1:
        raise ConfigError(f"{path}: frontmatter is never closed with a second `---` line")
    return text[3:end].strip("\n")


def _coerce_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [] if not inner else [p.strip().strip("'\"") for p in inner.split(",")]
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')) and len(raw) >= 2:
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        return raw


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """A minimal nested-mapping reader for this project's own shallow, 2-space-indented schema.

    Not a general YAML parser: it understands exactly what `sdd-flow.local.md` ever
    needs — nested mappings by indentation, scalars, inline `[a, b]` lists, and inline
    `{k: v, k: v}` maps (used for one tier profile per line). That is deliberately all;
    anything else in the file is a config-authoring mistake, not a case to silently handle.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, _, rest = line.strip().partition(":")
        rest = rest.strip()
        # Strip an inline `# comment` that is not inside a quoted or bracketed value.
        if rest and not rest.startswith(("'", '"', "[", "{")):
            rest = rest.split(" #", 1)[0].strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if rest == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        elif rest.startswith("{") and rest.endswith("}"):
            inner = rest[1:-1].strip()
            mapping: dict[str, Any] = {}
            for pair in inner.split(","):
                k, _, v = pair.partition(":")
                mapping[k.strip()] = _coerce_scalar(v)
            parent[key] = mapping
        else:
            parent[key] = _coerce_scalar(rest)
    return root


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate(cfg: dict[str, Any]) -> None:
    state_backend = cfg.get("state_backend")
    choices = IMPLEMENTED["state_backend"]
    if state_backend not in choices:
        raise ConfigError(f"state_backend: {state_backend!r} is not a recognized value")
    issue = choices[state_backend]
    if issue is not None:
        raise ConfigError(
            f"state_backend: {state_backend!r} is not implemented yet — tracked at {issue}. "
            f"Use one of: {', '.join(k for k, v in choices.items() if v is None)}."
        )
    classification = cfg.get("tiers", {}).get("classification")
    choices = IMPLEMENTED["tiers.classification"]
    if classification not in choices:
        raise ConfigError(f"tiers.classification: {classification!r} is not a recognized value")


def _normalize_profile_keys(parsed: dict[str, Any]) -> None:
    """Tier-profile keys come back as strings from the frontmatter reader (`"1"`); the
    defaults key them by int. Normalize in place so the merge below sees the same key
    for both, instead of silently keeping the default profile and adding an unused sibling."""
    profiles = parsed.get("tiers", {}).get("profiles")
    if isinstance(profiles, dict):
        parsed["tiers"]["profiles"] = {int(k): v for k, v in profiles.items()}


def load(repo: Path | str = ".", config_path: str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """The effective config for `repo`: defaults, deep-merged with the project's file if present."""
    path = Path(repo) / config_path
    if not path.is_file():
        cfg = DEFAULTS
    else:
        parsed = _parse_frontmatter(_frontmatter_text(path))
        _normalize_profile_keys(parsed)
        cfg = _deep_merge(DEFAULTS, parsed)
    _validate(cfg)
    return cfg


def tier_profile(cfg: dict[str, Any], tier: int) -> dict[str, Any]:
    """The profile for `tier` (0, 1 or 2): the project's override if given, else the default."""
    profiles = cfg.get("tiers", {}).get("profiles", DEFAULT_PROFILES)
    profile = profiles.get(tier)
    if profile is None:
        raise ConfigError(f"no tier profile configured for tier {tier}")
    return _deep_merge(DEFAULT_PROFILES.get(tier, {}), profile)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("usage: sdd_flow_config.py <repo> get <dotted.key> | get-tier-profile <0|1|2>", file=sys.stderr)
        return 2
    repo, command, *rest = argv
    try:
        cfg = load(repo)
        if command == "get" and rest:
            value: Any = cfg
            for part in rest[0].split("."):
                value = value[part]
            print(value)
            return 0
        if command == "get-tier-profile" and rest:
            import json

            print(json.dumps(tier_profile(cfg, int(rest[0]))))
            return 0
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (KeyError, TypeError):
        print(f"no such config key: {rest}", file=sys.stderr)
        return 1
    print("usage: sdd_flow_config.py <repo> get <dotted.key> | get-tier-profile <0|1|2>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
