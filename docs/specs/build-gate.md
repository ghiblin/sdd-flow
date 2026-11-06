# Build gate

## Security scanning step

**Goal:** Let a project optionally configure a security scanning step (SAST, dependency audit, secret scan) that runs alongside its build-gate command, so AI-generated code gets a visible security check before a sub-issue closes or a feature is marked verified, instead of relying only on whatever the project's own build-gate command happens to run.

**Architecture:** A new `security_commands` key in `.claude/sdd-flow.local.md` (read by `sdd_flow_config.py`, default `[]`) names zero or more `{name, run}` shell commands. `sdd-flow-tdd` step 8 and `sdd-flow-pr-validate` step 3 each run every configured command on the clean tree, right after the project's own build-gate command passes — on every build gate invocation, not only at `sdd-flow-pr-validate`. Each command's own exit code is its pass/fail signal: a non-zero exit fails the gate the same way a failing build-gate command does. On an all-zero-exit pass, the gate writes a second marker, alongside the existing build-gate marker from `gate_marker.py` (`sdd-gate/<tree>`), at a sibling `sdd-security/<tree>` path, keyed to the same `HEAD^{tree}`. `sdd_gate_guard.py`'s existing check for `set-stage.py <n> complete|verified` additionally requires the security marker to match the clean tree whenever `security_commands` is non-empty; when it is empty, the hook's behavior is unchanged.

**Out of scope:** Parsing a tool's own finding/severity output format (SARIF, SPDX, etc.) — a command's exit code is the only signal sdd-flow reads; a UI or aggregated report of findings beyond each failing command's own stdout/stderr; auto-fixing a finding; running the security step outside `sdd-flow-tdd`/`sdd-flow-pr-validate` (for example as a separate pre-commit hook).

**Criteria:**
- When `security_commands` is unset or empty, the build gate shall run with no security step and no security-marker requirement. [test: scripts/test_sdd_flow_config.py::test_security_commands_default_empty]
- When any configured `security_commands` entry exits non-zero on the clean tree, `sdd-flow-tdd` step 8 and `sdd-flow-pr-validate` step 3 shall treat the gate as failed, the same as a failing build-gate command. [test: scripts/test_run_security_commands.py::test_fails_when_any_command_exits_nonzero]
- When every configured `security_commands` entry exits zero on the clean tree, the gate shall write a security marker at `sdd-security/<HEAD^{tree}>`. [test: scripts/test_run_security_commands.py::test_writes_marker_when_all_commands_pass]
- While `security_commands` is non-empty, `sdd_gate_guard.py` shall deny `set-stage.py <n> complete|verified` unless both the build-gate marker and the security marker match the clean tree's `HEAD^{tree}`. [test: scripts/test_sdd_gate_guard.py::test_denies_complete_without_security_marker_when_configured]
- While `security_commands` is empty, `sdd_gate_guard.py` shall require only the existing build-gate marker, unchanged from its current behavior. [test: scripts/test_sdd_gate_guard.py::test_allows_complete_without_security_marker_when_unconfigured]

**Decisions:**
- A security command's own exit code is the only pass/fail signal; sdd-flow does not parse tool-specific severity output. A project encodes its desired severity threshold in the command's own CLI flags (for example `npm audit --audit-level=high`, `semgrep --severity=ERROR`), the same way the existing build-gate command is just a shell command sdd-flow runs without inspecting its output.
- The security step writes a second marker (`sdd-security/<tree>`), alongside the existing build-gate marker (`sdd-gate/<tree>`), so `sdd_gate_guard.py` can require both without changing the existing build-gate marker's format or meaning (see docs/adr/ADR-001-second-marker-file-for-the-security-scanning-step.md).
