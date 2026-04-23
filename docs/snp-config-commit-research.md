# SNP_CONFIG and SNP_COMMIT Research

## Overview

`SNP_CONFIG` and `SNP_COMMIT` are AMD SEV-SNP firmware ABI commands that allow
the hypervisor to manage platform configuration and firmware versioning. They are
exposed to Linux hosts through the `/dev/sev` device and wrapped by the
`snphost` CLI tool from the `virtee/snphost` project.

In the sev-certify project, these commands correspond to certification level
**3.0.0-1**, which adds `snphost config` and `snphost commit` testing on top of
the existing 3.0.0-0 (SNP Attestation) baseline.

---

## ABI Specification Details

Source: AMD SEV-SNP Firmware ABI Specification, Revision 1.58 (Document #56860)

### SNP_CONFIG (Command ID: 0x06B)

**Purpose:** Sets the system-wide configuration values for the SNP firmware.

**Platform State Requirement:** The platform must be in the **INIT** state.

**Input Parameters:**

| Field          | Size (bytes) | Description                                                    |
|----------------|-------------|----------------------------------------------------------------|
| REPORTED_TCB   | 8           | Desired TCB_VERSION to report in guest attestation reports     |
| MASK_CHIP_ID   | 4           | If set, the CHIP_ID field in attestation reports is zero-filled|
| MASK_CHIP_KEY  | 4           | If set, VCEK is mixed with zeros instead of chip unique key    |
| Reserved       | 0x3F0       | Reserved, must be zero                                         |

Total structure size: 1024 bytes (0x400).

**Behavior:**
- When `REPORTED_TCB` is non-zero, the firmware sets the internal
  `ReportedTcb` to the supplied value. All subsequent attestation reports will
  use this value and the VCEK will be derived from it.
- When `REPORTED_TCB` is zero, `ReportedTcb` is reset to `CurrentTcb`.
- The platform enforces the invariant `ReportedTcb <= CommittedTcb <= CurrentTcb`.
  `REPORTED_TCB` can be set to any value up to `CurrentTcb`; setting any field
  higher than `CurrentTcb` will fail with `INVALID_PARAM`. The hypervisor
  typically sets `REPORTED_TCB` at or below `CommittedTcb` to hide provisional
  firmware updates from guests.
- `MASK_CHIP_ID` and `MASK_CHIP_KEY` control privacy and key usage features.
  See [MASK_CHIP_ID and MASK_CHIP_KEY Use Cases](#mask_chip_id-and-mask_chip_key-use-cases)
  below for detailed behavior and use cases.

**Error Conditions:**
- `INVALID_LENGTH` - Input buffer too small.
- `INVALID_PLATFORM_STATE` - Platform is not in INIT state.
- `INVALID_PARAM` - Any field of `REPORTED_TCB` exceeds `CurrentTcb`.
- `INVALID_CONFIG` - A feature-specific constraint is violated (e.g., FMC
  field set when FMC is not enabled).

### SNP_COMMIT (Command ID: 0x068)

**Purpose:** Commits the currently running firmware version, preventing rollback
to any previously committed version.

**Platform State Requirement:** The platform must be in the **INIT** state.

**Input/Output Parameters:** None.

**Behavior:**
- Commits the current firmware version **and** the current microcode patch
  level. Sets `CommittedVersion` equal to `CurrentVersion` and `CommittedTcb`
  to `CurrentTcb` (including the MICROCODE field).
- After commit, the firmware will refuse to load any firmware image with a
  version less than the newly committed version.
- This operation is **irreversible**. There is no way to roll back after commit.

**Error Conditions:**
- `INVALID_PLATFORM_STATE` - Platform is not in INIT state.

### Related Command: SNP_CONFIG_EX (Command ID: 0x06Ch)

An extended version of `SNP_CONFIG` (available on Turin/EPYC 9005+) that
additionally supports setting the `FMC` (Firmware Migration Controller) TCB
field. The base behavior is identical to `SNP_CONFIG`.

---

## Key Concepts

### TCB_VERSION Structure

The Trusted Computing Base (TCB) version is a 64-bit value composed of several
component SVNs (Security Version Numbers):

| Field       | Bits   | Description                                   |
|-------------|--------|-----------------------------------------------|
| BOOT_LOADER | 7:0    | Bootloader SVN                                |
| TEE         | 15:8   | PSP OS SVN (TEE)                              |
| Reserved    | 23:16  | Reserved, must be zero                        |
| SNP         | 31:24  | SNP firmware SVN                              |
| Reserved    | 39:32  | Reserved, must be zero                        |
| FMC         | 47:40  | Firmware Migration Controller SVN (Turin+)    |
| Reserved    | 55:48  | Reserved, must be zero                        |
| MICROCODE   | 63:56  | CPU microcode patch level SVN                 |

### TCB Version Types

The firmware tracks multiple TCB versions simultaneously:

- **CurrentTcb**: Reflects the TCB of the currently loaded firmware and
  microcode. Updated automatically when firmware is loaded.
- **CommittedTcb**: The minimum TCB that has been committed. Firmware with a
  lower TCB than this cannot be loaded.
- **ReportedTcb**: The TCB reported in attestation reports and used for VCEK
  derivation. Defaults to `CurrentTcb` but can be overridden via `SNP_CONFIG`.
- **LaunchTcb**: The TCB value at the time `SNP_INIT` was called. Unlike
  `CurrentTcb`, this value does not change during live firmware updates,
  providing a stable reference for the TCB at platform initialization time.

### Platform State Machine

The SNP platform has two states relevant to config/commit:

1. **UNINIT**: Platform is uninitialized. Must call `SNP_INIT` or
   `SNP_INIT_EX` to move to INIT.
2. **INIT**: Platform is initialized. `SNP_CONFIG` and `SNP_COMMIT` are valid
   in this state. The ABI spec does not impose a guest count restriction on
   either command - they can be called while guests are running.

### MASK_CHIP_ID and MASK_CHIP_KEY Use Cases

These two fields in `SNP_CONFIG` control privacy and key usage at the platform
level. They are set system-wide and affect all subsequent attestation reports
and guest key derivations.

#### MASK_CHIP_ID

Controls whether the chip's unique hardware identifier appears in attestation
reports.

- **Value 0 (default):** The `CHIP_ID` field in attestation reports contains
  the chip's unique identifier (as output by `GET_ID`). This allows a verifier
  to identify the exact physical chip that produced the report.
- **Value 1 (masked):** The `CHIP_ID` field in attestation reports is
  zero-filled. The chip cannot be identified from the report.

*ABI Reference: Table 23 (ATTESTATION_REPORT), offset 0x1A0h (Section 7.3):*
> "If MaskChipId is set to 0, Identifier unique to the chip as output by
> GET_ID. Otherwise, set to 0h."

**Use cases for masking CHIP_ID:**
- **Fleet privacy:** In a cloud or data center environment, a CSP may not want
  tenants to know which specific physical chip their VM is running on. Masking
  CHIP_ID prevents workload tracking or fingerprinting across chip migrations.
- **Stable attestation baseline:** When VMs migrate between chips in a fleet,
  masking CHIP_ID ensures attestation reports have a consistent format
  regardless of which chip produces them, simplifying verification policies.
- **Policy consistency:** Uniform attestation reports across a fleet make it
  easier to write verification policies that don't need to enumerate or
  allowlist specific chip IDs.

#### MASK_CHIP_KEY

Controls whether the VCEK (Versioned Chip Endorsement Key) is used for
attestation report signing and guest key derivation.

- **Value 0 (default):** The firmware signs attestation reports using the VCEK
  (or VLEK if loaded) normally. Guest key derivation via `MSG_KEY_REQ` works
  as expected.
- **Value 1 (masked):** The firmware writes **zeroes** into the `SIGNATURE`
  field of attestation reports instead of signing them. Guest key derivation
  requests using VCEK (`ROOT_KEY_SELECT=0`) return `INVALID_KEY`.

*ABI Reference: Section 7.3 (Attestation), page 59:*
> "If MaskChipKey is 1, the firmware writes zeroes into the SIGNATURE field
> instead of signing the report."

*ABI Reference: Section 7.2 (Key Derivation), page 56:*
> "If ROOT_KEY_SELECT is 0 and MaskChipKey is 1, the firmware returns the
> INVALID_KEY status code to the guest."

**Use cases for masking CHIP_KEY:**
- **VLEK-only environments:** CSPs using VLEK (Versioned Loaded Endorsement
  Key) instead of VCEK can set `MASK_CHIP_KEY=1` to ensure no chip-specific
  key material is ever used. This forces all attestation through the
  CSP-provisioned VLEK path.
- **Disabling chip-bound attestation:** In environments where chip-specific
  attestation is not desired (e.g., testing, development, or privacy-sensitive
  deployments), masking the chip key prevents any chip-unique cryptographic
  material from being exposed.

#### Mask-Chip Value Encoding

The `snphost config set` command takes a single mask-chip parameter (0-3) that
encodes both fields:

| Value | Binary | MASK_CHIP_ID | MASK_CHIP_KEY | Effect                              |
|-------|--------|-------------|---------------|--------------------------------------|
| 0     | 00     | Disabled    | Disabled      | Full chip identity, VCEK signing     |
| 1     | 01     | Enabled     | Disabled      | Hidden chip ID, VCEK signing         |
| 2     | 10     | Disabled    | Enabled       | Visible chip ID, no VCEK signing     |
| 3     | 11     | Enabled     | Enabled       | Hidden chip ID, no VCEK signing      |

### Firmware Versioning (Committed vs Provisional)

- When `CommittedVersion == CurrentVersion`, the loaded firmware is
  **committed**.
- When `CommittedVersion < CurrentVersion`, the loaded firmware is
  **provisional** and can be rolled back.
- `SNP_COMMIT` transitions provisional firmware to committed status.

---

## Practical Usage via snphost CLI

The `snphost` tool wraps the kernel `/dev/sev` ioctls for these commands.

### Viewing Current TCB State

```bash
snphost show tcb
```

Displays the current Platform TCB and Reported TCB values.

### Setting Configuration (SNP_CONFIG)

```bash
snphost config set <BOOTLOADER> <TEE> <SNP-FW> <MICROCODE> <MASK-CHIP> [FMC]
```

- Parameters are positional: bootloader SVN, TEE SVN, SNP firmware SVN,
  microcode SVN, mask-chip value (0-3), and optionally FMC SVN (Turin+).
- Values can only be set to equal or lower versions than current.
- Changes the Reported TCB immediately but does **not** change Platform TCB.
- Mask-chip value is a 2-bit field:
  - Bit 0: `MASK_CHIP_ID` (0=disabled, 1=enabled)
  - Bit 1: `MASK_CHIP_KEY` (0=disabled, 1=enabled)

### Committing Configuration (SNP_COMMIT)

```bash
snphost commit
```

- Permanently commits the current firmware version and TCB.
- Prevents rollback to any previous firmware version.
- Resets Reported TCB to match Current TCB.
- **This is irreversible.**

### Resetting Uncommitted Changes

```bash
snphost config reset
```

- Discards any uncommitted configuration changes.
- Reverts Reported TCB to the last committed state.

---

## Why These Commands Exist

### Problem: Firmware Update VCEK Coupling

When a hypervisor updates SEV-SNP firmware, the firmware's TCB version changes.
Since the VCEK (Versioned Chip Endorsement Key) is derived from the TCB version,
a firmware update immediately changes the VCEK. This means:

1. Existing guests have attestation reports signed with the old VCEK.
2. New attestation reports would use a new VCEK.
3. Relying parties need time to obtain the new VCEK certificate from AMD's KDS.

### Solution: Decoupled Rollout with SNP_CONFIG

`SNP_CONFIG` allows the hypervisor to:
1. Install new firmware (provisional).
2. Set `ReportedTcb` to the old TCB version via `SNP_CONFIG`.
3. Continue serving attestation with the old VCEK while the new VCEK certificate
   propagates through the KDS.
4. Once ready, clear the `ReportedTcb` override and commit.

### Solution: Fleet Privacy and Policy with MASK_CHIP

`SNP_CONFIG` also allows the hypervisor to control chip-level privacy:
- **MASK_CHIP_ID** hides the chip's unique identifier from attestation reports,
  preventing workload tracking or chip fingerprinting across a fleet.
- **MASK_CHIP_KEY** disables VCEK-based signing entirely, useful in VLEK-only
  environments where the CSP provisions its own endorsement keys.

These settings enable consistent attestation policies across heterogeneous
fleets without exposing per-chip identity or key material.

### Solution: Anti-Rollback with SNP_COMMIT

`SNP_COMMIT` provides a security guarantee that once firmware is committed, the
platform cannot be downgraded to a vulnerable version. This is critical for
maintaining the security posture of the TCB.

---

## Relationship to Attestation

These commands directly affect attestation reports and the certificate chain
used to verify them.

### TCB Fields in the Attestation Report

The attestation report contains several TCB-related fields, each serving a
different verification purpose:

- **REPORTED_TCB**: The TCB version set by the hypervisor via `SNP_CONFIG`
  (defaults to `CurrentTcb` if not overridden). This is the TCB used for VCEK
  derivation and is the version the hypervisor vouches for.
- **COMMITTED_TCB**: The minimum committed TCB. A verifier should check:
  *"Does this TCB address all the vulnerabilities I care about?"* If
  `COMMITTED_TCB` is too low, the platform may be vulnerable to rollback.
- **CURRENT_TCB**: The TCB of the currently executing firmware and microcode.
  Informational - reflects what is actually running, which may be newer than
  what is reported.
- **LAUNCH_TCB**: The TCB at the time the guest was launched. Does not change
  during live firmware updates within a guest's lifetime.
- **CHIP_ID**: Connects the report to the VCEK certificate that signed it. If
  `MASK_CHIP_ID` is set, this field is zeroed.

### VCEK Derivation from REPORTED_TCB

The VCEK is derived by mixing the `REPORTED_TCB` SVN components into the chip's
unique secret via a Key Derivation Function (KDF):

```
Chip Unique Secret
  + BOOT_LOADER SVN (from REPORTED_TCB)
  + TEE SVN         (from REPORTED_TCB)
  + SNP FW SVN      (from REPORTED_TCB)
  + MICROCODE SVN   (from REPORTED_TCB)
  -> KDF -> VCEK (attestation signing key)
```

The VCEK signs the attestation report. The VCEK certificate is retrieved from
AMD's Key Distribution Service (KDS) and is part of a certificate chain:

```
AMD Root CA -> AMD SEV CA -> VCEK -> signs Attestation Report
```

Because the VCEK is derived from `REPORTED_TCB` (not `CurrentTcb`), changing
the Reported TCB via `SNP_CONFIG` changes which VCEK is used. This is what
allows the hypervisor to continue using an older VCEK during firmware
transitions.

### Linux Kernel Interfaces

- **Host side:** `/dev/sev` device - used for `SNP_CONFIG`, `SNP_COMMIT`, and
  other platform management commands.
- **Guest side:** `/dev/sev-guest` device - used for `SNP_GET_REPORT` (get
  attestation report) and `SNP_GET_EXT_REPORT` (get report with certificates).
  The host can pre-load certificates via `SNP_SET_EXT_CONFIG` so guests can
  retrieve them alongside the report.

---

## Testing Considerations

### What Can Be Tested Non-Destructively

- `snphost show tcb` - Read and verify current TCB values.
- `snphost config set` with current values - Set ReportedTcb to current values
  (no-op effectively, but exercises the code path).
- `snphost config set` with lower values - Set ReportedTcb to lower values,
  verify attestation reports reflect the change, then reset.
- `snphost config reset` - Reset after config changes.
- Verify attestation report TCB fields match expected values.

### What Is Destructive (Cannot Be Undone)

- `snphost commit` - Permanently commits firmware. On a test platform this is
  acceptable, but it prevents future rollback.

### Test Verification Points

1. After `config set`: Reported TCB should match the configured values.
2. After `config set`: Platform TCB should remain unchanged.
3. After `config reset`: Reported TCB should revert to Platform TCB.
4. After `commit`: Committed TCB should equal Current TCB.
5. Attestation reports should reflect the Reported TCB, not Current TCB.
6. Setting TCB values higher than current should fail.

---

## Sources

- AMD SEV-SNP Firmware ABI Specification, Rev 1.58 (Document #56860)
  - Section 8.3: SNP_COMMIT
  - Section 8.6: SNP_CONFIG
  - Section 8.7: SNP_CONFIG_EX
  - Section 3.2: Platform State Machine
  - Section 3.3: Live Firmware Updates
- AMD SEV-SNP Attestation: Establishing Trust in Guests (Linux Security
  Summit 2024, Jeremy Powell) - TCB version invariant, VCEK derivation,
  attestation report field verification guidance
- [virtee/snphost GitHub Repository](https://github.com/virtee/snphost)
- [SEV-SNP Firmware Hot-loading for KVM (KVM Forum)](https://gitlab.com/qemu-project/kvm-forum/-/raw/main/_attachments/2025/SEV_FW_Hotl_zfT5e9Y.pdf)
- [AMD SEV Developer Resources](https://www.amd.com/en/developer/sev.html)
- [Linux Kernel SEV Guest API Documentation](https://docs.kernel.org/virt/coco/sev-guest.html)
