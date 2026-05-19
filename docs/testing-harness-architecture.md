# Testing Harness Architecture

## Overview

This document describes the architecture for refactoring sev-certify from a
monolithic systemd boot pipeline into a repeatable testing harness. The central
change is extracting guest launch from a fixed pipeline stage into a callable
module that tests invoke on demand.

---

## 1. Current Architecture

### Pipeline

The current system is a linear systemd target chain baked into the host image.
Each target depends on the previous one; the entire sequence runs exactly once
per boot cycle.

```
                        HOST IMAGE (systemd)
  ┌─────────────────────────────────────────────────────────────────────┐
  │                                                                     │
  │  boot.target ─► system.target ─► launch.target ─► test.target       │
  │       │              │                │                │            │
  │   beacon-boot    snphost-ok     calculate-meas.    (host waits      │
  │                  journal-remote  launch-guest.sh    for guest)      │
  │                                  verify-guest                       │
  │                                      │                              │
  │                                      ▼                              │
  │                               QEMU SNP Guest                        │
  │                          ┌──────────────────────┐                   │
  │                          │ boot.target           │                  │
  │                          │   ▼                   │                  │
  │                          │ system.target         │                  │
  │                          │   snpguest-ok         │                  │
  │                          │   ▼                   │                  │
  │                          │ test.target           │                  │
  │                          │   attestation-workflow│                  │
  │                          │   ▼                   │                  │
  │                          │ report.target         │                  │
  │                          │   ▼                   │                  │
  │                          │ stop.target           │                  │
  │                          └──────────────────────┘                   │
  │                                      │                              │
  │  test.target ◄───── guest journal ───┘                              │
  │       │                                                             │
  │  report.target ─► stop.target                                       │
  │   display-guest-logs    login-or-reboot                             │
  │   sev-certificate-gen   beacon-report                               │
  │                                                                     │
  └─────────────────────────────────────────────────────────────────────┘
```

### Problems

1. **Single execution per boot** -- the whole chain runs once then reboots.
   Iterating on a single test requires a full reboot cycle.
2. **Guest launch is a pipeline stage** -- `launch-guest.sh` is hardcoded with
   a single QEMU configuration. Different tests cannot launch VMs with different
   SNP policies, images, or memory sizes.
3. **Guest communication is one-shot** -- journal upload works but is
   unidirectional (guest-to-host) with no ability for the host to send
   commands to the guest after boot.
4. **No host-only test stage** -- host-side tests (snphost config, commit,
   memfd) must currently be inserted as a new target (`host-test.target`),
   but still run exactly once in the linear chain.
5. **Tight coupling** -- test definitions, execution, and result collection are
   all interleaved across systemd services and shell scripts with no shared data
   model.

---

## 2. Proposed Architecture

### Harness Overview

The testing harness is a host-side orchestrator (Python) that reads
certification definitions from TOML files, iterates through tests, launches VMs
as needed, executes steps, and collects results.

```
                             HOST (bare metal or host image)
  ┌────────────────────────────────────────────────────────────────────────┐
  │                                                                        │
  │  ┌─────────────────────────────────────────────────────┐               │
  │  │              TESTING HARNESS (sev_certify)          │               │
  │  │                                                     │               │
  │  │  1. Load manifest from TOML                         │               │
  │  │  2. For each TestDefinition:                        │               │
  │  │     a. Import test module, call steps()             │               │
  │  │     b. If requires_vm: launch_guest(vm_profile)     │──────┐        │
  │  │     c. Execute host steps                           │      │        │
  │  │     d. Execute guest steps (via serial)             │      │        │
  │  │     e. Collect StepResults                          │      │        │
  │  │     f. If requires_vm: teardown_guest()             │      │        │
  │  │  3. Aggregate into CertificationResult              │      │        │
  │  │  4. Write report                                    │      │        │
  │  └─────────────────────────────────────────────────────┘      │        │
  │                                                               │        │
  │                       launch_guest() module                   │        │
  │                    ┌──────────────────────┐                   │        │
  │                    │  VMProfile → QEMU    │◄──────────────────┘        │
  │                    │  - image_path        │                            │
  │                    │  - ovmf_path         │                            │
  │                    │  - memory            │                            │
  │                    │  - policy            │                            │
  │                    │  - serial socket     │─────┐                      │
  │                    │  - host_data         │     │                      │
  │                    └──────────────────────┘     │                      │
  │                                                 │                      │
  │                                                 ▼                      │
  │                                        QEMU SNP Guest                  │
  │                                   ┌─────────────────────┐              │
  │                                   │  Serial listener    │              │
  │                                   │  /dev/ttyS1         │              │
  │                                   │    ▼                │              │
  │                                   │  Execute command    │              │
  │                                   │    ▼                │              │
  │                                   │  Return result JSON │              │
  │                                   └─────────────────────┘              │
  │                                                                        │
  └────────────────────────────────────────────────────────────────────────┘
```

### Key Differences from Current Architecture

| Aspect | Current (systemd pipeline) | Proposed (harness) |
|---|---|---|
| Orchestrator | systemd target ordering | Python script |
| Execution count | Once per boot | Repeatable without reboot |
| Guest launch | Fixed pipeline stage | Callable module per-test |
| VM configuration | Hardcoded single QEMU command | Parameterized by VMProfile |
| Test definitions | Implicit in systemd service ordering | TOML manifest + per-test Python modules |
| Host-guest comm | Journal upload (one-shot) | Serial console (dedicated) |
| Result collection | Journal + certificate generator | Structured JSON per step |
| Host-only tests | Require `host-test.target` insertion | Just steps with `runs_on: host` |

---

## 3. Data Model

### Struct Relationships

```
CertificationDefinition
├── version: string                    "3.0.0-0"
├── description: string                "SEV-SNP Attestation"
├── result: pass | fail | error | null
├── started_at: timestamp | null
├── completed_at: timestamp | null
├── tests[]: TestDefinition
│   ├── name: string                   "attestation-workflow"
│   ├── module: string                 "tests.attestation_workflow"
│   ├── scope: host | guest | mixed    determines VM requirement
│   ├── requires_vm: bool              derived from scope ≠ host
│   ├── vm_profile: string | null      key into [vm_profiles] table
│   ├── result: pass | fail | error | null
│   ├── started_at: timestamp | null
│   ├── completed_at: timestamp | null
│   │
│   └── steps[]: Step                  (populated by module at runtime)
│       ├── name: string               "generate-report"
│       ├── type: setup | required | info
│       ├── runs_on: host | guest
│       ├── command: string             "snpguest report ..."
│       ├── expected_result: string     "exit_code:0"
│       ├── timeout: int (seconds)      60
│       ├── result: pass | fail | error | skip | null
│       ├── exit_code: int | null
│       ├── stdout: string | null
│       ├── stderr: string | null
│       └── duration_ms: int | null
└── vm_profiles{}: VMProfile
    ├── image_path: string              "/path/to/guest.efi"
    ├── ovmf_path: string              "/usr/share/ovmf/OVMF.amdsev.fd"
    ├── memory: string                  "2048M"
    ├── serial_port: int                4444  (host-side unix socket ID)
    ├── policy: string                  "0x30000"
    ├── guest_visible_workarounds: string  "0x0"
    ├── id_block: string | null
    ├── id_auth: string | null
    ├── author_key_enabled: bool        false
    └── host_data: string | null        base64 or hex
```

### Decision: Combined Definition + Result Structs

**Decision**: Combined. Each struct carries both the definition fields (name,
command, expected_result) and the result fields (result, exit_code, stdout).

**Rationale**:

1. **Single file output** -- the certification report is a single artifact that
   contains what was tested AND what happened. No need to join two files.
2. **Result fields start null** -- before execution, result fields are null/empty.
   After execution, they are filled in. The struct is self-documenting about
   whether a step has run.
3. **Simpler code** -- the harness imports the test module, calls `steps()` to
   get the step list, executes them, writes results into the same structures,
   and serializes. No mapping between definition IDs and result IDs.
4. **Precedent** -- test frameworks (JUnit XML, TAP, pytest JSON) commonly
   combine test identity with test outcome in a single record.

### Decision: Steps Defined in Python, Not TOML

**Decision**: The TOML file declares *which* tests to run and their metadata
(name, scope, vm_profile). The *steps* for each test are defined in a Python
module referenced by the `module` field.

**Rationale**:

1. **TOML stays clean** -- the certification file is a short manifest, not a
   wall of `[[tests.steps]]` arrays with repeated boilerplate fields.
2. **Steps are code** -- step definitions benefit from variables, loops, helper
   functions, and imports. Multi-line shell commands embedded in TOML strings
   are unreadable and hard to maintain.
3. **Reuse** -- common step patterns (e.g., "run snpguest report then verify")
   can be shared across tests as plain Python functions.
4. **Type safety** -- the shared `models.py` provides `Step` as a dataclass.
   Test modules construct `Step` objects directly with IDE autocomplete and
   static analysis support.
5. **Per-test isolation** -- each test's logic lives in its own file. Adding a
   new test means adding one Python file and one `[[tests]]` entry in TOML.

### Field-Level Detail

#### CertificationDefinition

| Field | Type | Source | Description |
|---|---|---|---|
| `version` | string | TOML | Certification level (e.g., `"3.0.0-0"`) |
| `description` | string | TOML | Human-readable description |
| `tests` | TestDefinition[] | TOML | Ordered list of tests |
| `vm_profiles` | map[string]VMProfile | TOML | Named VM configurations |
| `result` | enum | Runtime | Overall pass/fail/error, null before run |
| `started_at` | ISO 8601 | Runtime | When the suite started |
| `completed_at` | ISO 8601 | Runtime | When the suite finished |

#### TestDefinition

| Field | Type | Source | Description |
|---|---|---|---|
| `name` | string | TOML | Unique test identifier |
| `module` | string | TOML | Dotted Python module path (e.g., `"tests.snphost_ok"`). The module must export a `steps()` function returning `list[Step]`. |
| `scope` | enum | TOML | `host`, `guest`, or `mixed` |
| `requires_vm` | bool | Derived | `true` if scope is `guest` or `mixed` |
| `vm_profile` | string? | TOML | Key into `vm_profiles` table; required if `requires_vm` |
| `steps` | Step[] | Module | Ordered list of steps, populated by calling `module.steps()` |
| `result` | enum | Runtime | pass if all required steps pass, fail if any required step fails |
| `started_at` | ISO 8601 | Runtime | When the test started |
| `completed_at` | ISO 8601 | Runtime | When the test finished |

#### Step

| Field | Type | Source | Description |
|---|---|---|---|
| `name` | string | Module | Step identifier, unique within test |
| `type` | enum | Module | `setup` (must pass, not scored), `required` (must pass for test to pass), `info` (logged but does not affect pass/fail) |
| `runs_on` | enum | Module | `host` or `guest` |
| `command` | string | Module | Shell command to execute |
| `expected_result` | string | Module | Validation expression (e.g., `"exit_code:0"`, `"stdout_contains:PASS"`) |
| `timeout` | int | Module | Max seconds before killing the step |
| `result` | enum | Runtime | `pass`, `fail`, `error`, `skip`, null before run |
| `exit_code` | int? | Runtime | Process exit code |
| `stdout` | string? | Runtime | Captured stdout (truncated to 64KB) |
| `stderr` | string? | Runtime | Captured stderr (truncated to 64KB) |
| `duration_ms` | int? | Runtime | Wall-clock execution time |

#### VMProfile

| Field | Type | Source | Description |
|---|---|---|---|
| `image_path` | string | TOML | Path to guest UKI/EFI image |
| `ovmf_path` | string | TOML | Path to OVMF firmware |
| `memory` | string | TOML | RAM size (e.g., `"2048M"`) |
| `serial_port` | int | TOML | Numeric identifier appended to the serial socket path (e.g., `4444` → `/tmp/sev-certify-serial-4444.sock`). Allows multiple VMs to coexist. Default: auto-assigned from PID. |
| `policy` | string | TOML | SNP launch policy hex value |
| `guest_visible_workarounds` | string | TOML | SNP workaround flags |
| `id_block` | string? | TOML | SNP identity block (base64) |
| `id_auth` | string? | TOML | SNP identity auth blob (base64) |
| `author_key_enabled` | bool | TOML | SNP author key flag |
| `host_data` | string? | TOML | Arbitrary data passed to guest at launch (base64). If set to `"auto_measurement"`, the harness computes the guest measurement hash and uses that. |

---

## 4. Serialization Format

**Decision**: TOML for certification manifests, Python for test definitions, JSON
for output results.

**Rationale**:

- **TOML for manifests** -- the certification file is a short, human-authored
  manifest declaring which tests to run and their VM profiles. TOML handles
  `[[tests]]` arrays and `[vm_profiles.*]` tables cleanly. No step definitions
  live here, so the files stay short.
- **Python for test definitions** -- each test module constructs `Step` objects
  using the shared `models.py` types. This gives full language features
  (variables, loops, helpers) and eliminates the readability problems of
  embedding multi-line shell commands in TOML strings.
- **JSON for results** -- machine-generated, consumed by reporting tools, no
  need for comments. JSON is the lingua franca for structured output.

---

## 5. Guest Launch Module

### Current State

`launch-guest.sh` is a monolithic script that:
1. Finds the OVMF binary
2. Reads a pre-computed measurement file
3. Computes `host_data` as sha256 of the measurement
4. Execs `qemu-system-x86_64` with hardcoded parameters

### Proposed Module: `lib/guest.py`

The guest launch module provides a `GuestVM` class:

```python
class GuestVM:
    """Manages a QEMU SEV-SNP guest VM lifecycle."""

    def __init__(self, profile: VMProfile) -> None: ...

    def launch(self) -> None:
        """Start QEMU with the given VMProfile. Blocks until guest signals READY."""
        ...

    def exec(self, command: str, timeout: int = 60) -> StepResult:
        """Execute a command in the guest via serial. Returns StepResult."""
        ...

    def teardown(self) -> None:
        """Send SHUTDOWN and wait for QEMU to exit."""
        ...
```

#### `GuestVM.launch()` Flow

```
GuestVM.launch()
  │
  ├─ 1. Validate VMProfile fields
  │     - image_path exists
  │     - ovmf_path exists
  │
  ├─ 2. Compute host_data if auto_measurement
  │     subprocess: snpguest generate measurement \
  │       --vcpu-type EPYC-v4 \
  │       --ovmf {ovmf_path} \
  │       --kernel {image_path} \
  │       --output-format hex
  │     → sha256 → base64
  │
  ├─ 3. Create serial socket path
  │     /tmp/sev-certify-serial-{pid}.sock
  │
  ├─ 4. Build QEMU command from VMProfile
  │     qemu-system-x86_64 \
  │       -enable-kvm \
  │       -machine q35 \
  │       -cpu EPYC-v4 \
  │       -machine memory-encryption=sev0 \
  │       -monitor none -display none \
  │       -object memory-backend-memfd,id=ram1,size={memory} \
  │       -machine memory-backend=ram1 \
  │       -object sev-snp-guest,id=sev0,cbitpos=51,reduced-phys-bits=1,\
  │              kernel-hashes=on,host-data="{host_data}",\
  │              policy={policy},\
  │              guest-visible-workarounds={guest_visible_workarounds}\
  │              [,id-block={id_block}][,id-auth={id_auth}]\
  │              [,author-key-enabled={author_key_enabled}] \
  │       -bios {ovmf_path} \
  │       -kernel {image_path} \
  │       -serial stdio \                              # console (ttyS0)
  │       -serial unix:{serial_sock},server=on,wait=off  # cmd (ttyS1)
  │
  ├─ 5. Launch QEMU via subprocess.Popen
  │     self.process = Popen(cmd)
  │
  └─ 6. Wait for guest ready signal on serial
        (guest writes "READY\n" to /dev/ttyS1 after boot)
```

#### Guest-Side Listener

The guest image includes a minimal serial listener that starts after boot:

```bash
# /usr/local/lib/scripts/serial-listener.sh (runs as systemd service)
exec 3<>/dev/ttyS1
echo "READY" >&3                    # Signal host that guest is up

while IFS= read -r line <&3; do
  cmd=$(echo "$line" | jq -r '.cmd // empty')
  timeout=$(echo "$line" | jq -r '.timeout // 60')

  if [ "$cmd" = "SHUTDOWN" ]; then
    echo '{"exit_code":0,"stdout":"shutting down"}' >&3
    poweroff
    break
  fi

  stdout=$(timeout "$timeout" bash -c "$cmd" 2>/tmp/stderr; echo $?)
  exit_code=$(tail -1 <<< "$stdout")
  stdout=$(head -n -1 <<< "$stdout")
  stderr=$(cat /tmp/stderr)

  jq -nc \
    --arg ec "$exit_code" \
    --arg out "$stdout" \
    --arg err "$stderr" \
    '{exit_code:($ec|tonumber), stdout:$out, stderr:$err}' >&3
done
```

This is intentionally minimal. It reads JSON command objects from `/dev/ttyS1`,
executes them, and writes JSON results back. The harness sends one command at a
time and reads one response.

---

## 6. Host-Guest Communication

### Decision: Dedicated Serial Port (Option 3 variant from evaluation doc)

**Selected**: A second ISA serial port (`ttyS1`) dedicated to command/response
traffic, separate from the console (`ttyS0`).

**Why not the other options** (referencing `docs/host-guest-communication-evaluation.md`):

| Option | Rejection reason |
|---|---|
| Journal upload (Option 1) | Unidirectional, one-shot per boot, requires network stack in guest |
| SSH (Option 2) | Heavyweight -- adds openssh-server to minimal UKI images, key management, network stack |
| Single serial (Option 3 as-is) | Console noise makes parsing unreliable |
| Virtio-serial (Option 4) | Requires custom protocol anyway; serial is simpler and already partially supported |
| QGA (Option 5) | Adds qemu-guest-agent package to guest, QMP is verbose with base64-encoded output |
| Vsock (Option 6) | Requires `vhost_vsock` module, custom protocol still needed, unverified with SEV-SNP |

**Why dedicated serial works well here**:

1. **No guest packages needed** -- `/dev/ttyS1` is a standard device, readable
   with basic shell utilities already present in the guest.
2. **No network stack** -- serial is a character device, no TCP/IP required.
3. **Clean channel** -- `ttyS0` carries kernel console output and `ttyS1`
   carries only command/response JSON. No parsing noise.
4. **Simple protocol** -- one JSON line per command, one JSON line per response.
   No framing, no multiplexing.
5. **Bidirectional** -- host can send commands and receive results.
6. **QEMU flag is trivial** -- just add `-serial unix:path,server=on,wait=off`.
7. **SEV-SNP compatible** -- ISA serial is not a virtio device, no IOMMU
   concerns.

### Protocol

```
Host → Guest (via serial socket):
  {"cmd": "snpguest report /tmp/r.bin /tmp/rng.bin --random", "timeout": 60}

Guest → Host (via serial socket):
  {"exit_code": 0, "stdout": "...", "stderr": ""}

Host → Guest (shutdown):
  {"cmd": "SHUTDOWN"}
```

One command, one response, synchronous. The harness blocks on the response with
a timeout.

---

## 7. Execution Flows

### 7.1 Host-Only Test

Example: `snphost-ok` checks.

```
Harness                                       Host
  │                                            │
  ├─ Load TestDefinition "snphost-ok"          │
  │   scope: host                              │
  │   requires_vm: false                       │
  │                                            │
  ├─ Step 1: "snphost-ok"                      │
  │   runs_on: host                            │
  │   command: "snphost ok"                    │
  │         ──────────────────────────────────►│
  │         ◄────────── exit_code=0 ────────── │
  │   result: pass                             │
  │                                            │
  ├─ Step 2: "snphost-show"                    │
  │   runs_on: host                            │
  │   command: "snphost show"                  │
  │         ──────────────────────────────────►│
  │         ◄────────── stdout + exit=0 ────── │
  │   result: pass                             │
  │                                            │
  └─ TestDefinition result: pass               │
     (no VM launched or torn down)             │
```

### 7.2 Guest-Only Test

Example: guest boot verification.

```
Harness                      Guest Launch Module             QEMU Guest
  │                               │                               │
  ├─ Load TestDefinition          │                               │
  │   scope: guest                │                               │
  │   requires_vm: true           │                               │
  │   vm_profile: "default"       │                               │
  │                               │                               │
  ├─ guest_launch("default") ────►│                               │
  │                               ├─ Build QEMU cmd from profile  │
  │                               ├─ Start QEMU ───────────────►  │
  │                               ├─ Wait for "READY" on serial   │
  │                               │◄──────── "READY" ───────────  │
  │◄──── GUEST_PID, SERIAL_SOCK──┤                                │
  │                               │                               │
  ├─ Step 1: "boot-check"        │                                │
  │   runs_on: guest              │                               │
  │   guest_exec("dmesg|grep SEV")───────────────────────────────►│
  │                               │◄───── {exit_code:0,...} ────  │
  │   result: pass                │                               │
  │                               │                               │
  ├─ guest_teardown() ───────────►│                               │
  │                               ├─ send SHUTDOWN ────────────►  │
  │                               ├─ wait for QEMU exit           │
  │                               │                           (exits)
  │◄──── done ───────────────────┤                                │
  │                               │                               │
  └─ TestDefinition result: pass  │                               │
```

### 7.3 Mixed Host+Guest Test

Example: attestation workflow -- host sets config, launches guest, guest
generates attestation report, host verifies report fields.

```
Harness                       Guest Module                QEMU Guest
  │                                │                            │
  ├─ Load TestDefinition           │                            │
  │   scope: mixed                 │                            │
  │   vm_profile: "snp-default"    │                            │
  │                                │                            │
  ├─ Step 1: "set-config"         │                             │
  │   runs_on: host                │                            │
  │   command: "snphost config     │                            │
  │     set reported_tcb ..."      │                            │
  │   ──► execute on host          │                            │
  │   result: pass                 │                            │
  │                                │                            │
  ├─ Step 2: "commit-config"      │                             │
  │   runs_on: host                │                            │
  │   command: "snphost commit"    │                            │
  │   ──► execute on host          │                            │
  │   result: pass                 │                            │
  │                                │                            │
  ├─ guest_launch("snp-default")──►│                            │
  │                                ├─ Start QEMU ────────────►  │
  │                                │◄────── READY ────────────  │
  │◄──── ready ───────────────────┤                             │
  │                                │                            │
  ├─ Step 3: "generate-report"    │                             │
  │   runs_on: guest               │                            │
  │   guest_exec("snpguest        │                             │
  │     report /tmp/r.bin          │                            │
  │     /tmp/rng.bin --random")────────────────────────────────►│
  │                                │◄───── {ec:0, ...} ───────  │
  │   result: pass                 │                            │
  │                                │                            │
  ├─ Step 4: "display-report"     │                             │
  │   runs_on: guest               │                            │
  │   guest_exec("snpguest        │                             │
  │     display report             │                            │
  │     /tmp/r.bin")───────────────────────────────────────────►│
  │                                │◄───── {ec:0, stdout} ────  │
  │   ◄── capture stdout           │                            │
  │   result: pass                 │                            │
  │                                │                            │
  ├─ Step 5: "verify-tcb"         │                             │
  │   runs_on: host                │                            │
  │   command: uses stdout from    │                            │
  │     step 4 to verify fields    │                            │
  │   result: pass                 │                            │
  │                                │                            │
  ├─ guest_teardown() ────────────►│                            │
  │                                ├─ SHUTDOWN ──────────────►  │
  │                                │                       (exits)
  │◄──── done ────────────────────┤                             │
  │                                │                            │
  └─ TestDefinition result: pass   │                            │
```

**Mixed test execution order**: Steps execute sequentially in definition order.
The VM is launched immediately before the first guest step and torn down
immediately after the last guest step.

1. Execute host steps that precede the first guest step (VM not yet launched).
2. Launch VM (using `vm_profile`).
3. Execute remaining steps in order through the last guest step. Host steps
   interleaved between guest steps run while the VM is up.
4. Teardown VM.
5. Execute any host steps that follow the last guest step (VM no longer running).

---

## 8. Test Lifecycle Diagram

Single test execution from the harness perspective:

```
                    ┌──────────────────────────────────┐
                    │  Read manifest from TOML         │
                    │  Import test modules             │
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────▼──────────────────┐
                    │  For each TestDefinition:        │
                    │  set result = null               │
                    │  set started_at = now()          │
                    └───────────────┬──────────────────┘
                                    │
                    ┌───────────────▼──────────────────┐
              ┌─NO──┤  requires_vm?                    │
              │     └───────────────┬──────────────────┘
              │                    YES
              │     ┌───────────────▼──────────────────────────────┐
              │     │  Any host steps before                       │
              │     │  first guest step?                ├─YES──► Execute them
              │     └───────────────┬──────────────────┘          │
              │                     │◄────────────────────────────┘
              │     ┌───────────────▼──────────────────┐
              │     │  guest_launch(vm_profile)        │
              │     │  Wait for READY signal           │
              │     └───────────────┬──────────────────┘
              │                     │
              ├─────────────────────┤
              │     ┌───────────────▼──────────────────────────────┐
              │     │  For each Step:                              │
              │     │  ┌───────────────────────────────┐           │
              │     │  │ runs_on == host?              │           │
              │     │  │  YES: exec on host            │           │
              │     │  │  NO:  guest_exec()            │           │
              │     │  └────────────┬──────────────────┘           │
              │     │               │                              │
              │     │  ┌────────────▼───────────────────┐          │
              │     │  │ Evaluate result vs             │          │
              │     │  │ expected_result                │          │
              │     │  │ Set step.result                │          │
              │     │  └────────────┬───────────────────┘          │
              │     │               │                              │
              │     │  ┌────────────▼───────────────────┐          │
              │     │  │ type==required &&              │          │
              │     │  │ result==fail?                  │          │
              │     │  │  YES: test fails,              │          │
              │     │  │       skip remaining           │          │
              │     │  │  NO:  continue                 │          │
              │     │  └────────────────────────────────┘          │
              │     └───────────────┬──────────────────────────────┘
              │                     │
              │     ┌───────────────▼──────────────────┐
              ├─NO──┤  VM running?                     │
              │     └───────────────┬──────────────────┘
              │                    YES
              │     ┌───────────────▼──────────────────┐
              │     │  guest_teardown()                │
              │     └───────────────┬──────────────────┘
              │                     │
              ├─────────────────────┘
              │
              ▼
  ┌───────────────────────────────┐
  │  Set test.result              │
  │  Set test.completed_at        │
  └───────────────┬───────────────┘
                  │
  ┌───────────────▼───────────────┐
  │  More tests?                  │
  │  YES: loop                    │
  │  NO:  compute suite result    │
  └───────────────┬───────────────┘
                  │
  ┌───────────────▼───────────────┐
  │  Write results JSON           │
  │  Write human report           │
  └───────────────────────────────┘
```

---

## 9. Repeatable Execution Without Rebooting

The harness runs on a live host and can be invoked repeatedly:

```bash
# Run certification level 3.0.0-0
python3 -m sev_certify certifications/3.0.0-0.toml

# Run again with a different guest image
python3 -m sev_certify certifications/3.0.0-0.toml --override vm_profiles.default.image_path=/tmp/custom.efi

# Run a single test by name
python3 -m sev_certify certifications/3.0.0-0.toml --test snphost-ok

# Run all levels
python3 -m sev_certify certifications/3.0.0-0.toml certifications/3.0.0-1.toml
```

This works because:

1. **No systemd target dependency** -- the harness is a plain script, not a
   systemd service. It does not require specific targets to be reached.
2. **Guest lifecycle is per-test** -- each test that needs a VM launches one and
   tears it down. No persistent VM across tests.
3. **No host state mutation** -- host-only tests (snphost ok, snphost show) are
   read-only queries. Tests that mutate state (snphost config/commit) are
   responsible for cleanup or run in a known-state-first order.
4. **Idempotent guest launch** -- each `guest_launch()` starts a fresh QEMU
   process with a fresh guest boot. No carryover state.

### Interaction with systemd pipeline

The harness replaces the systemd pipeline for development and CI. The systemd
pipeline can still exist for the "boot-and-certify" use case (USB stick
scenario) where the host boots, runs the harness via a systemd service, and
shuts down. The harness can be called from a single systemd service instead
of the current multi-target chain:

```ini
[Unit]
Description=Run SEV Certification Suite
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -m sev_certify /usr/local/lib/certifications/3.0.0-0.toml
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
```

---

## 10. Example Test Definitions

### Certification Manifest

The TOML file is a short manifest. Steps are not declared here -- each test
references a Python module that defines them.

```toml
# certifications/3.0.0-0.toml

version = "3.0.0-0"
description = "SEV-SNP Attestation - Level 3.0.0-0"

[vm_profiles.default]
image_path  = "/usr/local/lib/guest-image/guest.efi"
ovmf_path   = "/usr/share/ovmf/OVMF.amdsev.fd"
memory      = "2048M"
serial_port = 4444
policy      = "0x30000"
guest_visible_workarounds = "0x0"
author_key_enabled = false
host_data   = "auto_measurement"

[[tests]]
name   = "snphost-ok"
module = "tests.snphost_ok"
scope  = "host"

[[tests]]
name       = "attestation-workflow"
module     = "tests.attestation_workflow"
scope      = "mixed"
vm_profile = "default"
```

### Example 1: Host-Only Test Module

```python
# tests/snphost_ok.py

from sev_certify.models import Step

def steps() -> list[Step]:
    return [
        Step(
            name="snphost-ok",
            type="required",
            runs_on="host",
            command="snphost ok",
            expected_result="exit_code:0",
            timeout=30,
        ),
        Step(
            name="snphost-show-guests",
            type="info",
            runs_on="host",
            command="snphost show guests",
            expected_result="exit_code:0",
            timeout=10,
        ),
    ]
```

### Example 2: Mixed Host+Guest Test Module

```python
# tests/attestation_workflow.py

from sev_certify.models import Step

REPORT_BIN = "/tmp/attestation-report.bin"
REQUEST_DATA = "/tmp/random-request-data.bin"
CERTS_DIR = "/tmp/certificates"


def steps() -> list[Step]:
    return [
        # Host step: verify SNP is ready before launching guest
        Step(
            name="pre-check-snp",
            type="setup",
            runs_on="host",
            command="snphost ok",
            expected_result="exit_code:0",
            timeout=30,
        ),
        # Guest step: generate attestation report
        Step(
            name="generate-attestation-report",
            type="required",
            runs_on="guest",
            command=f"snpguest report {REPORT_BIN} {REQUEST_DATA} --random",
            expected_result="exit_code:0",
            timeout=60,
        ),
        # Guest step: fetch CA certificate chain
        Step(
            name="fetch-ca-certs",
            type="required",
            runs_on="guest",
            command=f"snpguest fetch ca pem -r {REPORT_BIN} {CERTS_DIR}",
            expected_result="exit_code:0",
            timeout=60,
        ),
        # Guest step: fetch VCEK certificate
        Step(
            name="fetch-vcek",
            type="required",
            runs_on="guest",
            command=f"snpguest fetch vcek pem {CERTS_DIR}/ {REPORT_BIN}",
            expected_result="exit_code:0",
            timeout=60,
        ),
        # Guest step: verify certificate chain
        Step(
            name="verify-cert-chain",
            type="required",
            runs_on="guest",
            command=f"snpguest verify certs {CERTS_DIR}/",
            expected_result="exit_code:0",
            timeout=30,
        ),
        # Guest step: verify attestation report
        Step(
            name="verify-attestation-report",
            type="required",
            runs_on="guest",
            command=f"snpguest verify attestation {CERTS_DIR}/ {REPORT_BIN}",
            expected_result="exit_code:0",
            timeout=30,
        ),
        # Guest step: display report for host-side validation
        Step(
            name="display-attestation-report",
            type="required",
            runs_on="guest",
            command=f"snpguest display report {REPORT_BIN}",
            expected_result="exit_code:0",
            timeout=10,
        ),
        # Guest step: validate request data matches report
        Step(
            name="validate-request-data",
            type="required",
            runs_on="guest",
            command=_validate_request_data_cmd(),
            expected_result="exit_code:0",
            timeout=10,
        ),
        # Guest step: validate measurement attribute
        Step(
            name="validate-measurement",
            type="required",
            runs_on="guest",
            command=_validate_measurement_cmd(),
            expected_result="exit_code:0",
            timeout=10,
        ),
    ]


def _validate_request_data_cmd() -> str:
    """Compare random request data against report's Report Data field."""
    return f"""\
random=$(xxd -p -c 0 {REQUEST_DATA} | tr '[:upper:]' '[:lower:]')
report=$(snpguest display report {REPORT_BIN} \
  | tr '\\n' ' ' \
  | sed 's|.*Report Data:\\(.*\\)Measurement.*|\\1|' \
  | sed 's| ||g' \
  | tr '[:upper:]' '[:lower:]')
[ "$random" = "$report" ]"""


def _validate_measurement_cmd() -> str:
    """Verify host-data matches sha256 of measurement."""
    return f"""\
expected=$(snpguest display report {REPORT_BIN} \
  | tr '\\n' ' ' \
  | sed 's|.*Host Data:\\(.*\\)ID Key Digest:.*|\\1|' \
  | sed 's| ||g' \
  | tr '[:upper:]' '[:lower:]')
actual=$(snpguest display report {REPORT_BIN} \
  | tr '\\n' ' ' \
  | sed 's|.*Measurement:\\(.*\\)Host Data.*|\\1|' \
  | sed 's| ||g' \
  | tr '[:upper:]' '[:lower:]' \
  | sha256sum | cut -d ' ' -f 1)
[ "$expected" = "$actual" ]"""
```

Note how Python eliminates the problems with inline TOML steps:
- Shared constants (`REPORT_BIN`, `CERTS_DIR`) avoid path duplication.
- Multi-line shell commands live in helper functions, not triple-quoted TOML.
- Adding a step is adding one `Step(...)` call -- no boilerplate field names.

---

## 11. Integration with host-test.target

The `host-test.target` insertion planned in
`docs/architecture-host-tests-before-launch.md` (for snphost config/commit,
memfd numa, key derivation, vlek loading) maps directly to the harness model:

- Each host-test becomes a `TestDefinition` with `scope: host`.
- No systemd target insertion needed -- the harness runs them as steps.
- The tests from cert level 3.0.0-1 that were planned as systemd services under
  `host-test.target` become TOML test definitions in
  `certifications/3.0.0-1.toml`.

The harness subsumes the `host-test.target` proposal. There is no need to
implement both.

---

## 12. Example Input and Output

### Input

Two files participate: the TOML manifest and the test module it references.
The TOML manifest is the same as shown in Section 10. The test modules are
`tests/snphost_ok.py` and `tests/attestation_workflow.py` (also shown above).

At runtime the harness:
1. Reads the TOML manifest.
2. For each `[[tests]]` entry, imports the `module` and calls `steps()`.
3. Populates `TestDefinition.steps` with the returned `Step` list.
4. Executes the steps (launching/tearing down VMs as needed).
5. Writes the combined definition + results as JSON.

### Output: `results/3.0.0-0-2026-05-18T12:00:00Z.json`

After running `python3 -m sev_certify certifications/3.0.0-0.toml`, the harness
produces:

```json
{
  "version": "3.0.0-0",
  "description": "SEV-SNP Attestation - Level 3.0.0-0",
  "result": "pass",
  "started_at": "2026-05-18T12:00:00Z",
  "completed_at": "2026-05-18T12:03:42Z",
  "vm_profiles": {
    "default": {
      "image_path": "/usr/local/lib/guest-image/guest.efi",
      "ovmf_path": "/usr/share/ovmf/OVMF.amdsev.fd",
      "memory": "2048M",
      "serial_port": 4444,
      "policy": "0x30000",
      "guest_visible_workarounds": "0x0",
      "author_key_enabled": false,
      "host_data": "auto_measurement"
    }
  },
  "tests": [
    {
      "name": "snphost-ok",
      "module": "tests.snphost_ok",
      "scope": "host",
      "requires_vm": false,
      "vm_profile": null,
      "result": "pass",
      "started_at": "2026-05-18T12:00:00Z",
      "completed_at": "2026-05-18T12:00:03Z",
      "steps": [
        {
          "name": "snphost-ok",
          "type": "required",
          "runs_on": "host",
          "command": "snphost ok",
          "expected_result": "exit_code:0",
          "timeout": 30,
          "result": "pass",
          "exit_code": 0,
          "stdout": "[ PASS ] - SEV: Enabled\n[ PASS ] - SNP: Enabled\n[ PASS ] - Firmware: OK",
          "stderr": "",
          "duration_ms": 1200
        },
        {
          "name": "snphost-show-guests",
          "type": "info",
          "runs_on": "host",
          "command": "snphost show guests",
          "expected_result": "exit_code:0",
          "timeout": 10,
          "result": "pass",
          "exit_code": 0,
          "stdout": "Guest count: 0",
          "stderr": "",
          "duration_ms": 800
        }
      ]
    },
    {
      "name": "attestation-workflow",
      "module": "tests.attestation_workflow",
      "scope": "mixed",
      "requires_vm": true,
      "vm_profile": "default",
      "result": "pass",
      "started_at": "2026-05-18T12:00:03Z",
      "completed_at": "2026-05-18T12:03:42Z",
      "steps": [
        {
          "name": "pre-check-snp",
          "type": "setup",
          "runs_on": "host",
          "command": "snphost ok",
          "expected_result": "exit_code:0",
          "timeout": 30,
          "result": "pass",
          "exit_code": 0,
          "stdout": "[ PASS ] - SEV: Enabled\n[ PASS ] - SNP: Enabled\n[ PASS ] - Firmware: OK",
          "stderr": "",
          "duration_ms": 1100
        },
        {
          "name": "generate-attestation-report",
          "type": "required",
          "runs_on": "guest",
          "command": "snpguest report /tmp/r.bin /tmp/rng.bin --random",
          "expected_result": "exit_code:0",
          "timeout": 60,
          "result": "pass",
          "exit_code": 0,
          "stdout": "",
          "stderr": "",
          "duration_ms": 3400
        },
        {
          "name": "verify-cert-chain",
          "type": "required",
          "runs_on": "guest",
          "command": "snpguest verify certs /tmp/certificates/",
          "expected_result": "exit_code:0",
          "timeout": 30,
          "result": "pass",
          "exit_code": 0,
          "stdout": "The AMD ARK was self-signed!\nThe AMD ASK was signed by the AMD ARK!\nThe VCEK was signed by the AMD ASK!",
          "stderr": "",
          "duration_ms": 2100
        },
        {
          "name": "display-report",
          "type": "required",
          "runs_on": "guest",
          "command": "snpguest display report /tmp/r.bin",
          "expected_result": "exit_code:0",
          "timeout": 10,
          "result": "pass",
          "exit_code": 0,
          "stdout": "Version: 2\nGuest SVN: 0\nPolicy: 0x30000\nMeasurement: a1b2c3...\nHost Data: d4e5f6...",
          "stderr": "",
          "duration_ms": 500
        }
      ]
    }
  ]
}
```

This JSON can be consumed by the existing certificate generator (adapted to
read JSON instead of journal entries) or by CI systems.

---

## 13. File Layout

```
sev-certify/
├── certifications/              # TOML manifests (what to run)
│   ├── 3.0.0-0.toml
│   └── 3.0.0-1.toml
├── tests/                       # Per-test Python modules (how to run)
│   ├── __init__.py
│   ├── snphost_ok.py            # steps() for snphost-ok test
│   ├── attestation_workflow.py  # steps() for attestation-workflow test
│   ├── snphost_config.py        # steps() for snphost config/commit test
│   └── ...
├── sev_certify/                 # Harness package (shared library)
│   ├── __init__.py
│   ├── __main__.py              # Entry point (python3 -m sev_certify)
│   ├── models.py                # Step, TestDefinition, VMProfile, etc.
│   ├── guest.py                 # GuestVM class (launch, exec, teardown)
│   ├── runner.py                # Test execution engine (imports test modules)
│   └── report.py                # Result formatting (JSON, human-readable)
├── results/                     # Output directory (gitignored)
│   └── 3.0.0-0-2026-05-18T12:00:00Z.json
├── modules/                     # Existing mkosi modules (unchanged)
│   ├── build/
│   ├── launch/
│   ├── test/
│   ├── report/
│   ├── system/
│   └── stop/
└── docs/
```

---

## 14. Open Questions and Future Work

1. **Python dependencies** -- the harness uses Python's stdlib `tomllib`
   (Python 3.11+) for TOML parsing and `subprocess` for command execution.
   No external packages are required. Host images need Python 3.11+.

2. **Step output cross-referencing** -- the `validate-measurement` step needs
   output from a previous step. Currently each step re-runs commands to
   extract data. Since test modules are Python, a future enhancement could
   use a shared context dict passed to `steps()` or use a callback-based
   step that receives prior results.

3. **Parallel step execution** -- all steps currently run sequentially. Parallel
   host steps could speed up host-only suites but adds complexity. Not needed
   for initial implementation.

4. **Certificate generation** -- the existing Python certificate generator reads
   from systemd journals. It needs to be adapted to read from the harness JSON
   output instead.

5. **CI integration** -- the harness JSON output can be converted to JUnit XML
   for CI systems. This is a straightforward post-processing step.

6. **Test module discovery** -- currently test modules are explicitly listed via
   `module` in TOML. A future option is auto-discovery (scan `tests/` for
   modules matching a naming convention), but explicit listing is preferred
   for now since certification order matters.
