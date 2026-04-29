# Module Flow Architecture

## Host

```
boot.target
  │  beacon-boot.service ──── beacon boot (log boot timestamp)
  │  snphost-ok.service ───── snphost ok (verify host SNP config)
  │
  ▼
system.target
  │  systemd-journal-remote ── listen :19532, store to /var/log/journal/guest-logs/
  │
  ▼
launch.target
  │  calculate-measurement.service
  │    └─ snpguest generate measurement
  │         inputs:  OVMF BIOS, guest UKI (guest.efi), VCPU type
  │         output:  /usr/local/lib/guest-image/guest_measurement.txt
  │
  │  launch-guest.service
  │    └─ read measurement → SHA256 → base64 → qemu-system-x86_64
  │         passes hash as sev-snp-guest host-data param
  │
  │  verify-guest.service
  │    └─ poll guest journal for "boot-successful" (60s timeout)
  │
  ▼
test.target
  │  (waits for guest-side attestation to complete via journal)
  │
  ▼
report.target
  │  display-guest-logs.service
  │    └─ poll guest journal for "Guest Tests Completed"
  │       extract logs from snpguest-ok + attestation-workflow services
  │
  │  sev-certificate-generator.service
  │    └─ generate_sev_certificate.py
  │         reads:  host journal (SNPHOST_TEST entries)
  │                 guest journal (SNPGUEST_TEST entries + attestation JSON)
  │         output: ~/sev_certificate_v3.0.0-0.txt
  │
  ▼
stop.target
     beacon-report.service
       └─ publish certificate to GitHub via beacon
     login-or-reboot.service
       └─ prompt user or reboot
```

## Guest

```
boot.target
  │  systemd-journal-upload ── connect to host http://10.0.2.2:19532
  │  boot-successful.service ─ log "boot-successful" (signals host)
  │
  ▼
system.target
  │  snpguest-ok.service ────── snpguest ok (verify guest SNP enablement)
  │  display-guest-environment ─ log guest env details
  │
  ▼
test.target
  │  attestation-workflow.service (snpguest_attestation.sh)
  │    ├─ 1. snpguest report  ─── generate attestation report + random request data
  │    ├─ 2. snpguest fetch ca ── fetch ARK/ASK from AMD KDS
  │    ├─ 3. snpguest fetch vcek ─ fetch VCEK for this TCB level
  │    ├─ 4. snpguest verify certs ── validate ARK → ASK → VCEK chain
  │    ├─ 5. snpguest verify attestation ── verify report signature via VCEK
  │    ├─ 6. snpguest display report
  │    └─ 7. validate report contents
  │         ├─ compare request data in report vs generated random data
  │         └─ compare SHA256(measurement) vs host-data field
  │
  │  output: /usr/local/lib/attestation_status (JSON with per-step pass/fail)
  │  journal: all results tagged SNPGUEST_TEST=3.0.0-0
  │
  ▼
report.target
  │  tests-finished.service ── log "Guest Tests Completed" (signals host)
  │
  ▼
stop.target
     (barrier — guest shutdown)
```

## Measurement verification loop

```
Host:  measurement_hex = snpguest generate measurement(OVMF, guest.efi, VCPU)
       measurement_hash = base64(SHA256(measurement_hex))
       → passed to QEMU as host-data

Guest: report = snpguest report (from SEV firmware)
       report.host_data == measurement_hash   ← confirms host identity
       SHA256(report.measurement) == report.host_data  ← confirms guest image integrity
```

## Data paths

| From | To | Data | Mechanism |
|------|----|------|-----------|
| calculate-measurement | launch-guest | measurement hex | file: `guest_measurement.txt` |
| launch-guest | QEMU/guest | measurement hash | QEMU `host-data` param |
| guest (all stages) | journal-remote | guest logs | systemd-journal-upload over HTTP :19532 |
| guest journal | certificate generator | test results | journalctl -D `/var/log/journal/guest-logs/` |
| certificate generator | beacon | certificate file | `~/sev_certificate_v3.0.0-0.txt` |
