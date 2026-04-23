# Test Plan: SNP_CONFIG and SNP_COMMIT (Certification Level 3.0.0-1)

## Objective

Add host-side tests for `snphost config` and `snphost commit` to the
sev-certify framework. These tests are part of certification level 3.0.0-1 as
defined in `docs/certifications.md`.

---

## Test Scope

These are **host-side** tests that run during the **system stage**, before guest
launch. They exercise the `snphost` CLI tool's `show tcb`, `config set`,
`config reset`, and `commit` subcommands against the platform's SEV-SNP firmware
via `/dev/sev`.

`SNP_CONFIG` and `SNP_COMMIT` require the platform to be in the INIT state but
do not impose a guest count restriction - they can be called while guests are
running. The tests are placed in the system stage for logical ordering (platform
configuration before guest launch), not due to an ABI constraint.

---

## Module Structure

Following the existing module patterns (e.g., `snphost-ok`), the new module
belongs in `modules/system/host/` since it runs during the system stage:

```
modules/system/host/
  snphost-config-commit/
    mkosi.extra/
      usr/local/lib/
        scripts/
          snphost_config_commit.sh        # Test script
        systemd/system/
          snphost-config-commit.service   # Systemd service unit
```

### Systemd Service Design

Following the pattern established by `snphost-ok.service`:

```ini
[Unit]
Description=Test snphost config and commit commands
DefaultDependencies=no
After=boot.target snphost-ok.service
Requires=boot.target snphost-ok.service

[Service]
Type=oneshot
ExecStart=/usr/local/lib/scripts/snphost_config_commit.sh
StandardOutput=journal+console
StandardError=journal+console
LogExtraFields="SEV_VERSION=3.0.0-1" "SNPHOST_TEST=3.0.0-1"

[Install]
WantedBy=system.target
```

Key design decisions:
- `After=snphost-ok.service` ensures the platform is confirmed SNP-ready first.
- `WantedBy=system.target` places the service in the system stage, before guest
  launch.
- Uses `LogExtraFields` with version `3.0.0-1` for the certificate generator to
  parse results.

---

## Test Cases

### Test 1: Read Current TCB Values

**Command:** `snphost show tcb`

**Purpose:** Baseline verification that the platform TCB can be read and parsed.

**Verification:**
- Command exits with status 0.
- Output contains both Platform TCB and Reported TCB values.
- Capture these values for use in subsequent tests.

### Test 2: Config Set with Lower Values (Verify Reported TCB Changes)

**Command:** `snphost config set <committed_bl - 1> <committed_tee> <committed_snp> <committed_ucode> 0`

**Purpose:** Verify that `config set` actually changes the Reported TCB. By
setting the bootloader SVN one version lower than the Committed TCB, we can
confirm the Reported TCB diverges from the Committed TCB. The `0` mask-chip
value leaves MASK_CHIP_ID and MASK_CHIP_KEY both disabled.

If the current bootloader SVN is 0 (cannot be decremented), the test should
try decrementing a different field (e.g., SNP firmware SVN). The key requirement
is that at least one field is set lower than the committed value.

This test validates the invariant `ReportedTcb <= CommittedTcb <= CurrentTcb`.
The ABI enforces that REPORTED_TCB must be <= CommittedTcb (not CurrentTcb).

**Verification:**
- Command exits with status 0.
- `snphost show tcb` confirms Reported TCB **differs** from Committed TCB.
- The decremented field in Reported TCB matches the value that was set.
- Committed and Platform TCB remain unchanged.

### Test 3: Config Reset (Verify Reported TCB Restores)

**Command:** `snphost config reset`

**Purpose:** Verify that config reset restores the Reported TCB back to match
the Committed TCB, undoing the change from Test 2.

**Verification:**
- Command exits with status 0.
- `snphost show tcb` confirms Reported TCB matches Committed TCB again.

### Test 4: Config Set with MASK_CHIP_ID Enabled

**Command:** `snphost config set <committed_bl> <committed_tee> <committed_snp> <committed_ucode> 1`

**Purpose:** Verify that the mask-chip parameter correctly sets MASK_CHIP_ID.
Value 1 enables MASK_CHIP_ID (hides chip ID in attestation reports) while
leaving MASK_CHIP_KEY disabled (VCEK signing still works).

**Verification:**
- Command exits with status 0.
- `snphost show tcb` confirms configuration was applied.

**Use case:** Fleet privacy - prevents workload tracking across chip migrations
in cloud environments by hiding the physical chip identifier.

### Test 5: Config Set with MASK_CHIP_KEY Enabled

**Command:** `snphost config set <committed_bl> <committed_tee> <committed_snp> <committed_ucode> 2`

**Purpose:** Verify that the mask-chip parameter correctly sets MASK_CHIP_KEY.
Value 2 leaves MASK_CHIP_ID disabled (chip ID visible) but enables MASK_CHIP_KEY
(disables VCEK-based signing - signatures will be zeroed).

**Verification:**
- Command exits with status 0.
- `snphost show tcb` confirms configuration was applied.

**Use case:** VLEK-only environments where CSPs provision their own endorsement
keys and want to ensure no chip-specific key material is used.

### Test 6: Config Set with Both Masks Enabled

**Command:** `snphost config set <committed_bl> <committed_tee> <committed_snp> <committed_ucode> 3`

**Purpose:** Verify that the mask-chip parameter correctly sets both MASK_CHIP_ID
and MASK_CHIP_KEY simultaneously. Value 3 enables both masks (chip ID hidden AND
VCEK signing disabled).

**Verification:**
- Command exits with status 0.
- `snphost show tcb` confirms configuration was applied.

**Use case:** Maximum privacy - no chip-unique data (ID or key) is exposed in
attestation reports.

### Test 7: Config Reset After Mask Changes

**Command:** `snphost config reset`

**Purpose:** Verify that config reset clears mask settings applied in Tests 4-6,
returning to the default state (both masks disabled).

**Verification:**
- Command exits with status 0.
- `snphost show tcb` confirms configuration has been reset.

### Test 8: Commit

**Command:** `snphost commit`

**Purpose:** Verify that the commit operation succeeds. This permanently commits
the current firmware version and microcode patch level.

**Verification:**
- Command exits with status 0.

**Note:** This is an irreversible operation. After commit, the platform will
refuse to boot with any firmware version older than the committed version. On
dedicated test hardware where firmware is not expected to be rolled back, this
is acceptable. The test commits the already-running firmware, so it does not
change the effective firmware version - it only prevents future downgrade.

---

## Test Script Design

The test script (`snphost_config_commit.sh`) follows the same patterns as
`snpguest_attestation.sh`:

1. **Status logging**: Each test step logs pass/fail as JSON to
   `/usr/local/lib/snphost_config_commit_status` for the certificate generator.
2. **Error handling**: Uses a `check_command_status` helper function matching
   the existing pattern in `snpguest_attestation.sh`.
3. **Sequential execution**: Tests run in order with early exit on failure.
4. **TCB parsing**: The script parses `snphost show tcb` output to extract
   individual TCB field values for use with `config set`. The exact output
   format should be verified on the target platform.

---

## Integration with Existing Framework

### mkosi.conf Change

Add the new module to `modules/system/host/mkosi.conf`:

```diff
 [Include]
 Include=./beacon-boot
 Include=./snphost-ok
+Include=./snphost-config-commit
 Include=./systemd-remote-journal
 Include=./system-done
```

### system-done.service Update

Add the new service to `system-done.service` dependencies so the system barrier
waits for config/commit tests to complete before proceeding to launch:

```diff
 [Unit]
 Description=Barrier that triggers the system services
 DefaultDependencies=no

-Requires=beacon-boot.service snphost-ok.service systemd-journal-remote.socket systemd-journal-remote.service
-After=beacon-boot.service snphost-ok.service systemd-journal-remote.socket systemd-journal-remote.service
+Requires=beacon-boot.service snphost-ok.service snphost-config-commit.service systemd-journal-remote.socket systemd-journal-remote.service
+After=beacon-boot.service snphost-ok.service snphost-config-commit.service systemd-journal-remote.socket systemd-journal-remote.service
```

### Service Ordering

The new service fits into the existing boot sequence as follows:

```
boot.target
  -> snphost-ok.service            -- confirms SNP is ready
  -> snphost-config-commit.service -- config/commit tests (NEW)
  -> system-done.service           -- barrier: system stage complete
  -> system.target
    -> launch.target               -- launches guest
      -> test.target               -- guest-side tests
        -> report.target           -- report generation
```

### Certificate Generator Updates (Future Scope)

The certificate generator (`sev_certificate_version_3_0_0_0.py`) will need
updates in a future iteration to:
- Parse the new `3.0.0-1` log entries.
- Include config/commit test results in the certification report.

This is out of scope for the initial test implementation.

---

## Files to Create

| File | Purpose |
|------|---------|
| `modules/system/host/snphost-config-commit/mkosi.extra/usr/local/lib/scripts/snphost_config_commit.sh` | Test script |
| `modules/system/host/snphost-config-commit/mkosi.extra/usr/local/lib/systemd/system/snphost-config-commit.service` | Systemd service unit |

## Files to Modify

| File | Change |
|------|--------|
| `modules/system/host/mkosi.conf` | Add `Include=./snphost-config-commit` |
| `modules/system/host/system-done/mkosi.extra/usr/local/lib/systemd/system/system-done.service` | Add `snphost-config-commit.service` to `Requires=` and `After=` |

---

## Risks and Considerations

1. **snphost commit is irreversible**: The commit test permanently sets the
   minimum firmware version. This is acceptable on dedicated test hardware
   where firmware is not expected to be rolled back.

2. **Platform state requirements**: Config and commit commands require the
   platform to be in INIT state. The ABI spec does not restrict these commands
   based on guest count, so they can be called while guests are running.
   The tests are placed before guest launch for logical ordering.

3. **snphost availability**: The `snphost` binary is already downloaded and
   installed by `modules/build/host/snphost/`. No additional build changes
   are needed.

4. **TCB value parsing**: The test script needs to parse TCB values from
   `snphost show tcb` output. The exact output format should be verified on
   the target platform to ensure correct parsing.

5. **FMC field (Turin+)**: On EPYC 9005+ hardware, the `config set` command
   accepts an optional 6th parameter for the FMC SVN. The test script should
   detect whether FMC is supported and pass the appropriate number of
   arguments.
