"""`sdd-flow-tdd` step 8, `sdd-flow-pr-validate` step 3 and `sdd-flow-reconcile` step 2
must each call `scripts/run_security_commands.py` on the clean tree, right after the
project's own build-gate command passes, on every build gate invocation (see
docs/specs/build-gate.md#Security scanning step, Architecture).

These tests read the two skills' own prose and fail until each numbered step's text
names the runner script, so a skill text that silently drifts from the spec's promised
wiring is caught the same way a missing implementation would be.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = "run_security_commands.py"


def _step_line(skill_md: Path, step: int) -> str:
    pattern = re.compile(rf"^{step}\.\s")
    for line in skill_md.read_text(encoding="utf-8").splitlines():
        if pattern.match(line):
            return line
    raise AssertionError(f"step {step} not found in {skill_md}")


class TestSecurityScanWiring(unittest.TestCase):
    def test_tdd_step_8_runs_the_security_command_runner(self):
        line = _step_line(REPO_ROOT / "skills/sdd-flow-tdd/SKILL.md", 8)
        self.assertIn(RUNNER, line)

    def test_pr_validate_step_3_runs_the_security_command_runner(self):
        line = _step_line(REPO_ROOT / "skills/sdd-flow-pr-validate/SKILL.md", 3)
        self.assertIn(RUNNER, line)

    def test_reconcile_step_2_runs_the_security_command_runner(self):
        line = _step_line(REPO_ROOT / "skills/sdd-flow-reconcile/SKILL.md", 2)
        self.assertIn(RUNNER, line)


if __name__ == "__main__":
    unittest.main()
