"""snphost-ok: Verify SNP is enabled and functional on the host."""

from sev_verify.models import Step


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
