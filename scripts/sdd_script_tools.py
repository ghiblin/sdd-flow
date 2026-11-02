"""Shared helpers of the SDD check scripts: the exit-2 error, the tool runner, the arg parser,
the JSON reader and the loader of the skills' `open_decisions.py`.

`sdd_check_state.py`, `graphify_refresh.py`, `check_pub_items.py` and `sdd_route.py` import it, so
a change to how a tool call fails (a missing binary, output that is not UTF-8, a non-zero exit)
lands once.
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess


class ToolError(Exception):
    """A usage or tool failure; the caller exits 2."""


def run_tool(cmd: list[str], cwd=None, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a tool; a missing binary or output that is not UTF-8 is a tool error, not exit 1."""
    try:
        if not capture:
            return subprocess.run(cmd, cwd=cwd)
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=cwd)
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"cannot run {' '.join(cmd[:2])}: {exc}") from exc


def run_checked(cmd: list[str], cwd=None) -> str:
    """Run a tool and return its stdout; a non-zero exit is a tool error."""
    result = run_tool(cmd, cwd)
    if result.returncode != 0:
        raise ToolError(f"{' '.join(cmd[:2])} failed: {result.stderr.strip() or cmd[-1]}")
    return result.stdout


def parse_json(raw: str, kind: type):
    """Parse tool output as JSON of the given top-level type; anything else is a tool error."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ToolError(f"cannot parse gh output: {exc}") from exc
    if not isinstance(data, kind):
        raise ToolError("cannot parse gh output: unexpected shape")
    return data


def load_open_decisions(path):
    """Load a copy of the skills' shared open_decisions helper; a missing or broken copy is a tool error."""
    try:
        spec = importlib.util.spec_from_file_location("open_decisions", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"no module spec for {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:  # noqa: BLE001 - any failure to load the helper is a tool error
        raise ToolError(f"cannot load {path}: {exc}") from exc


class Parser(argparse.ArgumentParser):
    """An argparse parser whose every exit is a ToolError, so a usage error is exit 2.

    It has no -h/--help: argparse exits 0 after the help text, which a caller reads as a pass.
    """

    def __init__(self, *args, usage_text: str = "", **kwargs):
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self.usage_text = usage_text

    def error(self, message: str):
        raise ToolError(f"{self.usage_text} ({message})" if self.usage_text else message)

    def exit(self, status: int = 0, message: str | None = None):
        raise ToolError(message.strip() if message else f"argparse exit {status}")
