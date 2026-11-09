# ADR-001: Second marker file for the security scanning step

**Status:** Accepted

## Context
Issue #3 adds an optional, configurable security scanning step (SAST, dependency audit, secret scan) that must run alongside the project's build-gate command on every build gate invocation (sdd-flow-tdd step 8 and sdd-flow-pr-validate step 3), and sdd_gate_guard.py must deny set-stage.py <n> complete|verified when that step fails, the same way it already denies it without a build-gate marker. The existing build-gate marker (gate_marker.py, sdd-gate/<tree>) is shared infrastructure that every SDD feature relies on, so how the security step's pass/fail state gets tracked affects more than this one module.

## Decision
Write a second marker file, sdd-security/<tree>, parallel to the existing sdd-gate/<tree> build-gate marker, rather than extending the existing marker's file format to also encode security status. sdd_gate_guard.py requires both markers to match the clean tree's HEAD^{tree} for set-stage.py <n> complete|verified whenever security_commands is non-empty; it is unaffected when security_commands is empty.

## Consequences
Keeps the existing build-gate marker's format and meaning stable for every feature that predates this change. Rules in a simple, additive mechanism (a second marker directory, same write/check pattern as gate_marker.py) instead of a schema migration on the existing marker file. Rules out ever encoding multiple gate results in one marker file without a further migration; a future third gate type would need its own marker directory in the same pattern.
