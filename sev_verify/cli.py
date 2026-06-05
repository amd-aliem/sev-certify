"""CLI arg parsing and entry point for sev_verify."""

from __future__ import annotations

import argparse
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    CertificationDefinition,
    CertificationResult,
    StepResult,
    TestDefinition,
    TestResult,
)
from .runner import load_steps, run_step

_LINE_WIDTH = 80


def _load_test_entries(toml_path: Path, data: dict) -> list[TestDefinition]:
    """Parse tests array from TOML data and return TestDefinition instances."""
    raw_tests = data.get("tests", [])
    if not isinstance(raw_tests, list):
        raise ValueError(f"{toml_path}: 'tests' must be an array of tables")

    tests: list[TestDefinition] = []
    for i, entry in enumerate(raw_tests):
        if not isinstance(entry, dict):
            raise ValueError(f"{toml_path}: tests[{i}] must be a table")
        try:
            tests.append(TestDefinition(**entry))
        except TypeError as exc:
            raise ValueError(f"{toml_path}: tests[{i}] has invalid fields: {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"{toml_path}: tests[{i}]: {exc}") from exc
    return tests


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sev_verify",
        description="SEV-SNP certification testing harness",
    )
    parser.add_argument(
        "path_to_guest",
        help="Path to the guest image/UKI",
    )
    parser.add_argument(
        "--version",
        "-v",
        dest="versions",
        action="append",
        default=[],
        help="Certification version(s) to run (e.g. 3.0). Repeatable. "
        "If omitted, all cert_tests/*/manifest.toml are used.",
    )
    return parser.parse_args(argv)


def load_manifest(toml_path: Path) -> CertificationDefinition:
    """Load and validate a TOML certification manifest."""
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except OSError as exc:
        raise ValueError(f"Cannot read manifest {toml_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Malformed TOML in {toml_path}: {exc}") from exc

    for key in ("version", "description"):
        if key not in data:
            raise ValueError(f"{toml_path}: missing required key {key!r}")

    tests = _load_test_entries(toml_path, data)

    return CertificationDefinition(
        version=str(data["version"]),
        description=str(data["description"]),
        tests=tests,
    )


def load_prereqs(cert_dir: Path) -> list[TestDefinition]:
    """Load prerequisite tests from cert_tests/common/prereqs.toml."""
    prereqs_path = cert_dir / "common" / "prereqs.toml"
    if not prereqs_path.exists():
        return []

    try:
        with open(prereqs_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot load prereqs {prereqs_path}: {exc}") from exc

    return _load_test_entries(prereqs_path, data)


def discover_manifests(cert_dir: Path, versions: list[str]) -> list[Path]:
    """Find all manifest.toml files in cert_tests/ subdirectories."""
    if not cert_dir.is_dir():
        return []

    if not versions:
        return sorted(cert_dir.glob("*/manifest.toml"))

    manifest_paths = []
    for version in versions:
        subfolder = "c" + version.replace(".", "_")
        mpath = cert_dir / subfolder / "manifest.toml"
        if not mpath.exists():
            print(f"Error: no manifest for version {version!r} "
                  f"(expected {mpath})", file=sys.stderr)
            continue
        manifest_paths.append(mpath)

    return manifest_paths


# ── Output helpers ───────────────────────────────────────────────

_RESULT_LABEL = {"pass": "PASS", "fail": "FAIL", "error": "ERR!", "skip": "SKIP"}
_IS_TTY = sys.stdout.isatty()


def _flush(msg: str, end: str = "\n") -> None:
    """Print and immediately flush so output appears in real time."""
    print(msg, end=end, flush=True)


def _section(label: str) -> None:
    """Print a section header with consistent width."""
    prefix = f"── {label} "
    _flush(f"{prefix}{'─' * (_LINE_WIDTH - len(prefix))}")


def _fmt_duration(ms: int | None) -> str:
    """Format a duration for display."""
    if ms is None:
        return ""
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms}ms"


def _step_result_line(sr: StepResult, is_last: bool) -> str:
    connector = "└─" if is_last else "├─"
    icon = _RESULT_LABEL.get(sr.result, "????")
    duration = _fmt_duration(sr.duration_ms)
    suffix = f" {duration} [{icon}]" if duration else f" [{icon}]"
    name_part = f"   {connector} {sr.step.name} "
    avail = _LINE_WIDTH - len(name_part) - len(suffix)
    dots = "·" * max(avail, 2)
    return f"{name_part}{dots}{suffix}"


# ── Live execution + output ──────────────────────────────────────


def execute_test(test: TestDefinition, guest_path: Path) -> TestResult:
    """Run a test, printing each step live as it executes."""
    started_at = datetime.now(timezone.utc).isoformat()
    step_results: list[StepResult] = []

    if test.description:
        name_part = f"   {test.name} "
        desc_part = f" {test.description}"
        avail = _LINE_WIDTH - len(name_part) - len(desc_part)
        _flush(f"{name_part}{' ' * max(avail, 2)}{desc_part}")
    else:
        _flush(f"   {test.name}")

    try:
        steps = load_steps(test)
    except Exception as exc:
        _flush(f"   [ERR!] — failed to load module: {exc}")
        return TestResult(
            test=test, result="error", step_results=[],
            started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(),
        )

    overall = "pass"
    total_steps = len(steps)

    for i, step in enumerate(steps):
        is_last = i == total_steps - 1

        # Guest-side steps can't run yet
        if step.runs_on == "guest":
            sr = StepResult(step=step, result="skip")
            step_results.append(sr)
            _flush(_step_result_line(sr, is_last))
            continue

        if _IS_TTY:
            connector = "└─" if is_last else "├─"
            _flush(f"   {connector} {step.name} ...", end="\r")

        sr = run_step(step, guest_path)
        step_results.append(sr)

        _flush(_step_result_line(sr, is_last))

        if sr.result in ("fail", "error"):
            if sr.stderr:
                gutter = "   " if is_last else "│  "
                for line in sr.stderr.strip().splitlines()[:5]:
                    _flush(f"   {gutter}   {line}")
            if step.type == "setup":
                overall = "fail"
                for j, remaining in enumerate(steps[i + 1:], i + 1):
                    skip = StepResult(step=remaining, result="skip")
                    step_results.append(skip)
                    _flush(_step_result_line(skip, j == total_steps - 1))
                break
            elif step.type == "required":
                overall = "fail"

    passed = sum(1 for s in step_results if s.result == "pass")
    failed = sum(1 for s in step_results if s.result in ("fail", "error"))
    icon = _RESULT_LABEL.get(overall, "????")
    counts = f"{passed}/{total_steps} passed" if not failed else f"{failed}/{total_steps} failed"
    suffix = f" {counts} [{icon}]"
    name_part = f"   result:"
    avail = _LINE_WIDTH - len(name_part) - len(suffix)
    _flush(f"{name_part}{' ' * max(avail, 2)}{suffix}")

    return TestResult(
        test=test, result=overall, step_results=step_results,
        started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(),
    )


def execute_certification(
    cert: CertificationDefinition, guest_path: Path,
) -> CertificationResult:
    """Run all tests in a certification with live output."""
    started_at = datetime.now(timezone.utc).isoformat()
    test_results: list[TestResult] = []
    overall = "pass"

    _section(f"Certification {cert.version}")
    _flush(f"   {cert.description}")
    _flush("")

    current_level = None
    for test in cert.tests:
        if test.level != current_level:
            if test.level:
                _flush(f"   ── {test.level} ──")
            current_level = test.level

        tr = execute_test(test, guest_path)
        test_results.append(tr)
        if tr.result != "pass":
            overall = tr.result
        _flush("")

    icon = _RESULT_LABEL.get(overall, "????")
    passed = sum(1 for t in test_results if t.result == "pass")
    label = f"   Certification {cert.version}:"
    suffix = f" {passed}/{len(test_results)} passed [{icon}]"
    _flush(f"{label}{' ' * max(_LINE_WIDTH - len(label) - len(suffix), 2)}{suffix}")
    _flush("")

    return CertificationResult(
        certification=cert, result=overall, test_results=test_results,
        started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    guest_path = Path(args.path_to_guest)

    if not guest_path.exists():
        print(f"Error: guest path does not exist: {guest_path}", file=sys.stderr)
        return 1

    cert_dir = Path(__file__).resolve().parent / "cert_tests"

    manifest_paths = discover_manifests(cert_dir, args.versions)

    if not manifest_paths:
        print(
            "Error: no manifest.toml found in cert_tests/*/",
            file=sys.stderr,
        )
        return 1

    _flush(f"   Guest: {guest_path}")
    _flush("")

    run_start = time.monotonic()
    total_tests = 0
    total_passed = 0

    # ── Run prerequisites (once, gates all certifications) ───────
    prereqs = load_prereqs(cert_dir)
    if prereqs:
        _section("Prerequisites")
        _flush("")
        prereq_results = []
        for test in prereqs:
            tr = execute_test(test, guest_path)
            prereq_results.append(tr)
            _flush("")

        total_tests += len(prereq_results)
        total_passed += sum(1 for r in prereq_results if r.result == "pass")

        if any(r.result != "pass" for r in prereq_results):
            label = "   Prerequisites:"
            suffix = f" {total_passed}/{total_tests} passed [FAIL]"
            _flush(f"{label}{' ' * max(_LINE_WIDTH - len(label) - len(suffix), 2)}{suffix}")
            _flush("   Skipping all certifications.")
            return 1
        label = "   Prerequisites:"
        suffix = f" {total_passed}/{total_tests} passed [PASS]"
        _flush(f"{label}{' ' * max(_LINE_WIDTH - len(label) - len(suffix), 2)}{suffix}")
        _flush("")

    # ── Run certifications ───────────────────────────────────────
    cert_results: list[CertificationResult] = []
    for manifest_path in manifest_paths:
        cert = load_manifest(manifest_path)
        cr = execute_certification(cert, guest_path)
        cert_results.append(cr)
        total_tests += len(cr.test_results)
        total_passed += sum(1 for tr in cr.test_results if tr.result == "pass")

    # ── Summary ──────────────────────────────────────────────────
    elapsed = time.monotonic() - run_start
    _section("Summary")
    for cr in cert_results:
        # Find the highest level where all tests passed
        highest_passing = None
        for tr in cr.test_results:
            if not tr.test.level:
                continue
            if tr.result == "pass":
                highest_passing = tr.test.level
            else:
                break
        icon = _RESULT_LABEL.get(cr.result, "????")
        level_info = f" (level {highest_passing})" if highest_passing else ""
        label = f"   Certification {cr.certification.version}:{level_info}"
        suffix = f" [{icon}]"
        _flush(f"{label}{' ' * max(_LINE_WIDTH - len(label) - len(suffix), 2)}{suffix}")
    _flush("")

    return 1 if any(cr.result != "pass" for cr in cert_results) else 0
