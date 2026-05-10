"""Boltz-2 validator.

Wraps `Boltz-2 <https://github.com/jwohlwend/boltz>`_ (MIT for both code and
weights). Boltz-2 takes a target+binder spec and produces:

- ``ipTM``, ``pAE_interaction`` from the structure prediction
- ``affinity_pred_value`` (continuous, higher = stronger predicted binder)
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
from pathlib import Path
from typing import Any

import yaml

from bindsight.validate.protocol import ValidationResult

LOG = logging.getLogger(__name__)

DEFAULT_BOLTZ2_VERSION = "2.0.1"


class MissingValidationError(FileNotFoundError):
    """Raised when validation output for a binder hasn't been produced yet."""


def build_boltz_yaml(
    *,
    target_id: str,
    target_sequence: str,
    binder_id: str,
    binder_sequence: str,
    predict_affinity: bool = True,
) -> dict:
    """Build the YAML config Boltz-2 expects on stdin.

    See https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md for
    the full schema. We stay on the documented happy path (two protein chains
    + one affinity property) so the spec is portable across Boltz-2 minor
    versions.
    """
    spec: dict[str, Any] = {
        "version": 1,
        "sequences": [
            {"protein": {"id": "T", "sequence": target_sequence}},
            {"protein": {"id": binder_id, "sequence": binder_sequence}},
        ],
    }
    if predict_affinity:
        spec["properties"] = [{"affinity": {"binder": binder_id}}]
    return spec


def write_boltz_yaml(spec: dict, path: Path) -> Path:
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
    confidence_path = next(output_dir.glob("confidence_*.json"), None)
    affinity_path = next(output_dir.glob("affinity_*.json"), None)

    iptm = pae_interaction = affinity_value = affinity_prob = None

    if confidence_path is not None:
        try:
            cdata = json.loads(confidence_path.read_text())
            iptm = _safe_float(cdata.get("iptm"))
            pae_interaction = _safe_float(
                cdata.get("pae_interaction") or cdata.get("interface_pae")
            )
        except (json.JSONDecodeError, OSError) as e:
            LOG.warning("failed to parse %s: %s", confidence_path, e)

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
        pae_interaction=pae_interaction,
        affinity_pred_value=affinity_value,
        affinity_probability_binary=affinity_prob,
        validator_name="boltz2",
        validator_version=DEFAULT_BOLTZ2_VERSION,
        notes=(
            f"parsed confidence={'yes' if confidence_path else 'no'}, "
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
    version = DEFAULT_BOLTZ2_VERSION
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
