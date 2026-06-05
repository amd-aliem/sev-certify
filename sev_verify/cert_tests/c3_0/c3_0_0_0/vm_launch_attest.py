"""vm-launch-attest: Launch SEV-SNP guest and verify attestation report.

Placeholder — real implementation pending VM launch module.
"""

from sev_verify.models import Step


def steps() -> list[Step]:
    return [
        Step(
            name="vm-launch-dummy",
            type="required",
            runs_on="host",
            command="true",  # placeholder until VM launch module is ready
            expected_result="exit_code:0",
            timeout=10,
        ),
    ]
