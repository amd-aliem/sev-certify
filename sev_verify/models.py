"""Data model dataclasses for sev_verify."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, get_args


# Single source of truth for the enum values
StepType = Literal["setup", "required", "info"]
RunsOn = Literal["host", "guest"]
Scope = Literal["host", "guest", "mixed"]


@dataclass
class Step:
    """A single executable step within a test."""

    name: str
    type: StepType
    runs_on: RunsOn
    command: str
    expected_result: str  # e.g. "exit_code:0", "stdout_contains:PASS"
    timeout: int = 60

    def __post_init__(self) -> None:
        if not self.name: 
            raise ValueError("Step.name must not be empty")
        if not self.command:
            raise ValueError(f"Step {self.name!r}: command must not be empty")
        if self.type not in get_args(StepType):
            raise ValueError(
                    f"Step {self.name!r}: invalid type {self.type!r}; "
                    f"expected one of {get_args(StepType)}"
                    )
        if self.runs_on not in get_args(RunsOn):
            raise ValueError(
                    f"Step {self.name!r}: invalid runs_on {self.runs_on!r}; "
                    f"expected one of {get_args(RunsOn)}"
                    )
        if self.timeout <= 0:
            raise ValueError(
                    f"Step {self.name!r}: timeout must be positive, got {self.timeout}"
                    )
        kind, sep, value = self.expected_result.partition(":")
        if kind not in ("exit_code", "stdout_contains") or not sep:
            raise ValueError(
                    f"Step {self.name!r}: invalid expected_result {self.expected_result!r}; "
                    f"expected 'exit_code:<int>' or 'stdout_contains:<string>'"
                    )
        if kind == "exit_code":
            try:
                int(value)
            except ValueError:
                raise ValueError(
                        f"Step {self.name!r}: exit_code value must be an integer, "
                        f"got {value!r}"
                        )


@dataclass
class TestDefinition:
    """A test declared in the TOML manifest."""

    name: str
    module: str  # dotted module path, e.g. "cert_tests.common.snphost_ok"
    scope: Scope
    description: str = ""
    level: str = ""  # certification level, e.g. "3.0.0-0"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("TestDefinition.name must not be empty")
        if not self.module:
            raise ValueError(f"TestDefinition {self.name!r}: module must not be empty")
        if self.scope not in get_args(Scope):
            raise ValueError(
                    f"TestDefinition {self.name!r}: invalid scope {self.scope!r}; "
                    f"expected one of {get_args(Scope)}"
                    )

    @property
    def requires_vm(self) -> bool:
        return self.scope in ("guest", "mixed")


@dataclass
class CertificationDefinition:
    """Top-level certification suite loaded from a TOML manifest."""

    version: str
    description: str
    tests: list[TestDefinition] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("CertificationDefinition.version must not be empty")


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
