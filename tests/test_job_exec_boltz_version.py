# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-interpreter validator provenance must come from the executed worker."""

import pytest

from bindsight.runners import job_exec
from bindsight.validate.protocol import UNRECORDED_VERSION

COMMAND = ["/managed/boltz/python", "-m", "bindsight.runners.boltz_compat", "predict"]


@pytest.mark.parametrize("version", ["2.0.3", "2.0.3+bindsight.1"])
def test_actual_worker_version_is_parsed_from_its_successful_receipt(version):
    assert (
        job_exec._observed_boltz_version(
            COMMAND, f"Other model output\nbindsight: Boltz {version} precision=32\r\nComplete\n"
        )
        == version
    )


@pytest.mark.parametrize(
    "stdout",
    [
        "No version recorded\n",
        "bindsight: Boltz 2.0.4 precision=32\n",
        "bindsight: Boltz 2.0.3 precision=unknown\n",
        "bindsight: Boltz 2.0.3 precision=32\n" * 2,
        "embedded bindsight: Boltz 2.0.3 precision=32\n",
    ],
)
def test_missing_unknown_or_ambiguous_managed_version_is_rejected(stdout):
    with pytest.raises(RuntimeError, match="version receipt"):
        job_exec._observed_boltz_version(COMMAND, stdout)


def test_custom_executable_cannot_inherit_controllers_boltz_version():
    assert (
        job_exec._observed_boltz_version(
            ["/custom/boltz", "predict"], "bindsight: Boltz 2.0.3 precision=32\n"
        )
        == UNRECORDED_VERSION
    )
