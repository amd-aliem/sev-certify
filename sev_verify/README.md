# sev_verify

Host-side testing harness for SEV-SNP certification. Reads TOML manifests that declare which tests to run, imports per-test Python modules that define executable steps, and orchestrates execution across host and guest environments.

## Usage

```bash
# Run a specific certification level
python3 -m sev_verify /path/to/guest.efi -v 3.0

# Run multiple levels
python3 -m sev_verify /path/to/guest.efi -v 3.0 -v 3.1

# Run all certifications found in cert_tests/
python3 -m sev_verify /path/to/guest.efi
```

## How it works

1. Discover manifests at `cert_tests/*/manifest.toml`. Each manifest declares test entries (name, scope, module path).

2. For each test, import its Python module from the same `cert_tests/<level>/` directory and call `steps()` to get the ordered list of `Step` objects. Steps specify a shell command, where it runs (host or guest), what constitutes success, and a timeout.

3. Execute steps sequentially. Host steps run locally via subprocess. Guest steps are sent to the VM over a dedicated serial channel (`ttyS1`). For tests with `scope: guest` or `scope: mixed`, a QEMU SNP guest is launched before the first guest step and torn down after the last.

4. Write results to `results/`.

## Layout

```
sev_verify/              Harness package
  cli.py                 CLI arg parsing + entry point
  models.py              Step, TestDefinition, CertificationDefinition
  cert_tests/            Certification levels
    common/              Shared test modules
      snphost_ok.py      Test modules
      ...
    cert_3_0/            Level 3.0
      manifest.toml      What to run
      ...
results/                 Output (gitignored)
```

## Requirements

Python 3.11+ (uses `tomllib` from stdlib). No external packages.
