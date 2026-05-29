"""CLI arg parsing and entry point for sev_verify."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .models import CertificationDefinition, TestDefinition


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
            # unknown or missing fields in the [[tests]] table
            raise ValueError(f"{toml_path}: tests[{i}] has invalid fields: {exc}") from exc
        except ValueError as exc:
            # failed __post_init__ validation (bad scope, empty name, ...)
            raise ValueError(f"{toml_path}: tests[{i}]: {exc}") from exc

    return CertificationDefinition(
        version=str(data["version"]),
        description=str(data["description"]),
        tests=tests,
    )



def discover_manifests(cert_dir: Path, versions: list[str]) -> list[Path]:
    """Find all manifest.toml files in cert_tests/ subdirectories."""
    if not cert_dir.is_dir():
        return []

    if not versions:
        return sorted(cert_dir.glob("*/manifest.toml"))

    manifest_paths = []
    for version in versions:
        subfolder = "cert_" + version.replace(".", "_")
        mpath = cert_dir / subfolder / "manifest.toml"
        if not mpath.exists():
            print(f"Error: no manifest for version {version!r} "
                  f"(expected {mpath})", file=sys.stderr)
            continue
        manifest_paths.append(mpath)

    return manifest_paths


def print_certification(cert: CertificationDefinition) -> None:
    """Print certification header."""
    header = f" Certification {cert.version} "
    print(f"──{header}{'─' * (60 - len(header))}")
    print(f"   {cert.description}")


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

    print(f"   Guest: {guest_path}")
    print()

    for manifest_path in manifest_paths:
        cert = load_manifest(manifest_path)
        print_certification(cert)
        print()

    return 0
