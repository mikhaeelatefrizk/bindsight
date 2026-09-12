# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Boltz-2 validator.

Wraps `Boltz-2 <https://github.com/jwohlwend/boltz>`_ (MIT for both code and
weights). Boltz-2 takes a target+binder spec and produces:

- ``ipTM``, ``pAE_interaction`` from the structure prediction
- ``affinity_pred_value`` (continuous, log(IC50)-like: **lower = stronger**
  predicted binder; the ranker inverts it). Ligand-only, so it stays ``None``
  for the protein binders bindsight designs.
- ``affinity_probability_binary`` (probability the design is a binder vs decoy)

This module's responsibility is the *parsing + composition* layer:

- :func:`build_boltz_yaml` produces the YAML config Boltz-2 ingests.
- :func:`parse_boltz_output` reads Boltz's output JSON into a
  :class:`bindsight.validate.protocol.ValidationResult`.
- :class:`Boltz2Validator` is the plugin entry point used by the orchestrator.

The actual GPU inference happens in the runner (Colab / Modal / local Docker)
because Boltz-2 needs CUDA. Calling :meth:`Boltz2Validator.validate` from the
orchestrator either:

1. Reads pre-computed Boltz output from the run's ``validate/`` directory
   (when the runner has already returned results), OR
2. Raises :class:`MissingValidationError` with a clear message pointing the
   user at the runner step.
"""

from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any

import yaml

from bindsight.validate.protocol import (
    UNRECORDED_VERSION,
    ValidationResult,
    installed_version,
)

LOG = logging.getLogger(__name__)

#: The Boltz-2 release this project pins, audited and installed.
#:
#: Single source of truth: ``bindsight.runners.tools.BOLTZ_PIP`` is built from
#: it. The dependency runs that way round because ``tools`` already imports this
#: module.
PINNED_BOLTZ2_VERSION = "2.0.3"


def installed_boltz_version() -> str | None:
    """The Boltz-2 actually importable here, or ``None`` where there is none.

    ``validator_version`` used to be :data:`PINNED_BOLTZ2_VERSION` written
    straight into every metrics row, which made it a label rather than a record:
    the pin was a range, so any 2.x could have produced a number, and the row
    said ``2.0.1`` regardless. A provenance field that reports a constant is
    worse than an absent one, because it answers the question wrongly instead of
    leaving it open.

    Returns ``None`` rather than the pin when Boltz is not installed — which is
    the case wherever the parser runs outside the GPU environment. Substituting
    the pinned version there would recreate the same fiction one level down.
    """
    return installed_version("boltz")


class MissingValidationError(FileNotFoundError):
    """Raised when validation output for a binder hasn't been produced yet."""


def build_boltz_yaml(
    *,
    target_id: str,
    target_sequence: str,
    binder_id: str,
    binder_sequence: str,
    predict_affinity: bool = True,
) -> dict[str, Any]:
    """Build the YAML config Boltz-2 expects on stdin.

    See https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md for
    the full schema. We stay on the documented happy path (two protein chains
    + one affinity property) so the spec is portable across Boltz-2 minor
    versions.
    """
    # Boltz-2 chain IDs must be short identifiers (single letters), not our
    # binder_id tracking string ("binder_0_seq0" makes Boltz-2 skip the input).
    # Use target_id for the target chain and a distinct single letter for the
    # binder; binder_id is kept only for our own bookkeeping/filenames.
    binder_chain = "B" if target_id != "B" else "C"
    spec: dict[str, Any] = {
        "version": 1,
        "sequences": [
            {"protein": {"id": target_id, "sequence": target_sequence}},
            {"protein": {"id": binder_chain, "sequence": binder_sequence}},
        ],
    }
    if predict_affinity:
        spec["properties"] = [{"affinity": {"binder": binder_chain}}]
    return spec


def write_boltz_yaml(spec: dict[str, Any], path: Path) -> Path:
    """Write a Boltz-2 spec dict to disk as YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    return path


def parse_boltz_output(
    *,
    output_dir: Path,
    binder_id: str,
    target_uniprot: str,
) -> ValidationResult:
    """Parse Boltz-2's per-design output directory into a ValidationResult.

    Boltz-2 writes one ``predictions/<run>/`` directory per spec, containing:

    - ``confidence_<run>_model_0.json``  — per-residue + interface confidence
      (we extract ``iptm`` and ``ptm``).
    - ``affinity_<run>.json`` (when affinity prediction enabled) —
      ``affinity_pred_value`` and ``affinity_probability_binary``.

    Both files are read; missing fields become ``None`` (not an error — the
    user may have disabled affinity prediction).
    """
    # Boltz writes to <out_dir>/predictions/<name>/confidence_*.json, so search
    # recursively (rglob) rather than only the top level.
    #
    # *Every* one of them, not the first. With --diffusion_samples > 1 Boltz
    # writes one per draw and ranks them by confidence descending, so
    # ``model_0`` is the best draw rather than a representative one. Reading
    # whichever file turned up first therefore reported a maximum over k — an
    # estimate that improves as more samples are bought, with no change to the
    # design. Averaging is the estimate of the distribution's centre; the best
    # draw is not an estimate of anything.
    confidence_paths = sorted(output_dir.rglob("confidence_*.json"))
    affinity_path = next(output_dir.rglob("affinity_*.json"), None)

    iptm = pae_interaction = affinity_value = affinity_prob = None
    iptm_samples: list[float] = []
    pae_samples: list[float] = []

    for path in confidence_paths:
        try:
            cdata = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            LOG.warning("failed to parse %s: %s", path, e)
            continue
        value = _safe_float(cdata.get("iptm"))
        if value is not None:
            iptm_samples.append(value)
        pae = _safe_float(cdata.get("pae_interaction") or cdata.get("interface_pae"))
        if pae is not None:
            pae_samples.append(pae)

    if iptm_samples:
        iptm = statistics.fmean(iptm_samples)
    if pae_samples:
        pae_interaction = statistics.fmean(pae_samples)

    if affinity_path is not None:
        try:
            adata = json.loads(affinity_path.read_text())
            affinity_value = _safe_float(adata.get("affinity_pred_value"))
            affinity_prob = _safe_float(adata.get("affinity_probability_binary"))
        except (json.JSONDecodeError, OSError) as e:
            LOG.warning("failed to parse %s: %s", affinity_path, e)

    return ValidationResult(
        binder_id=binder_id,
        target_uniprot=target_uniprot,
        iptm=iptm,
        iptm_n_samples=len(iptm_samples) or None,
        iptm_sd=statistics.stdev(iptm_samples) if len(iptm_samples) > 1 else None,
        pae_interaction=pae_interaction,
        affinity_pred_value=affinity_value,
        affinity_probability_binary=affinity_prob,
        validator_name="boltz2",
        validator_version=installed_boltz_version() or UNRECORDED_VERSION,
        notes=(
            f"parsed confidence={len(confidence_paths)} sample(s), "
            f"affinity={'yes' if affinity_path else 'no'}"
        ),
    )


def _safe_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class Boltz2Validator:
    """Plugin: Boltz-2 structure + affinity prediction.

    The validator class itself is a thin parser; the GPU inference happens
    in whichever runner the user picks (Colab / Modal / local Docker). The
    orchestrator (``bindsight validate``) is responsible for shipping the
    spec to the runner and pulling back the JSON outputs into
    ``<run>/validate/<binder_id>/``.
    """

    name = "boltz2"
    version = PINNED_BOLTZ2_VERSION
    license_notice = "Boltz-2: MIT (code + weights). Commercial-OK."

    def validate(
        self,
        target_uniprot: str,
        binder_id: str,
        binder_sequence: str,
        target_structure_path: str,
    ) -> ValidationResult:
        """Look up Boltz-2 output for this binder + parse it.

        Looks in ``<cwd>/validate/<binder_id>/`` for the JSONs Boltz-2 wrote.
        Raises :class:`MissingValidationError` if not found — the orchestrator
        catches this and prints a hint about running the GPU step first.
        """
        cwd = Path("validate") / binder_id
        if not cwd.exists():
            raise MissingValidationError(
                f"no Boltz-2 output found at {cwd}; "
                "run the GPU validation step first (see docs/colab-design-howto.md)"
            )
        return parse_boltz_output(
            output_dir=cwd,
            binder_id=binder_id,
            target_uniprot=target_uniprot,
        )
