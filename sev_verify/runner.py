"""Test runner: load modules, execute steps, collect results."""

from __future__ import annotations

import subprocess
import time
from importlib import import_module
from pathlib import Path

from .models import Step, StepResult, TestDefinition


def _check_expected(step: Step, proc: subprocess.CompletedProcess[str]) -> bool:
    """Check a step's expected_result against the process outcome."""
    kind, _, value = step.expected_result.partition(":")
    if kind == "exit_code":
        return proc.returncode == int(value)
    if kind == "stdout_contains":
        return value in (proc.stdout or "")
    # Unknown check type — treat as failure
    return False


def load_steps(test: TestDefinition) -> list[Step]:
    """Import a test module and call its steps() function."""
    # Module paths in the manifest are relative to sev_verify, e.g.
    # "cert_tests.cert_3_0.vm_launch_attest" → "sev_verify.cert_tests.cert_3_0.vm_launch_attest"
    fq_module = f"sev_verify.{test.module}"
    mod = import_module(fq_module)
    return mod.steps()


def run_step(step: Step, guest_path: Path) -> StepResult:
    """Execute a single step and return its result."""
    # Build the command line.  The guest_path is exposed as $GUEST_PATH
    # so scripts can use it, and also passed as $1 when the command is
    # an executable file (not a shell expression).
    env = {**__import__("os").environ, "GUEST_PATH": str(guest_path)}

    cmd_path = Path(step.command)
    if cmd_path.is_file():
        args: str | list[str] = [str(cmd_path), str(guest_path)]
        shell = False
    else:
        args = step.command
        shell = True

    start = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            timeout=step.timeout,
            capture_output=True,
            text=True,
            shell=shell,
            env=env,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return StepResult(
            step=step,
            result="error",
            stderr=f"Timed out after {step.timeout}s",
            duration_ms=duration_ms,
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return StepResult(
            step=step,
            result="error",
            stderr=str(exc),
            duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    passed = _check_expected(step, proc)

    return StepResult(
        step=step,
        result="pass" if passed else "fail",
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_ms=duration_ms,
    )


