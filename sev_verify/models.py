"""Data model dataclasses for sev_verify."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ── Definition models (loaded from TOML manifests) ──────────────


@dataclass
class Step:
    """A single executable step within a test."""

    name: str
    type: Literal["setup", "required", "info"]
    runs_on: Literal["host", "guest"]
    command: str
    expected_result: str  # e.g. "exit_code:0", "stdout_contains:PASS"
    timeout: int = 60


@dataclass
class TestDefinition:
    """A test declared in the TOML manifest."""

    name: str
    module: str  # dotted module path, e.g. "cert_tests.common.snphost_ok"
    scope: Literal["host", "guest", "mixed"]

    @property
    def requires_vm(self) -> bool:
        return self.scope in ("guest", "mixed")


@dataclass
class CertificationDefinition:
    """Top-level certification suite loaded from a TOML manifest."""

    version: str
    description: str
    tests: list[TestDefinition] = field(default_factory=list)


# ── Runtime result models (populated during execution) ──────────


@dataclass
class StepResult:
    """Result of executing a single Step."""

    step: Step
    result: Literal["pass", "fail", "error", "skip"]
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_ms: int | None = None


@dataclass
class TestResult:
    """Result of executing a TestDefinition."""

    test: TestDefinition
    result: Literal["pass", "fail", "error"]
    step_results: list[StepResult] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class CertificationResult:
    """Result of executing a CertificationDefinition."""

    certification: CertificationDefinition
    result: Literal["pass", "fail", "error"]
    test_results: list[TestResult] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
