#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Score a fetched design+validation results tarball into the benchmark result.

The GPU runners (Kaggle / Colab) return a ``<handle>.tar.gz`` containing
``metrics.jsonl`` (one validator row per design) plus ``design/`` and
``validate/``. This script turns that into the committed benchmark artifacts —
``results.json`` (the :mod:`bindsight.benchmark.designer_bench` schema, marked
``is_mock=False``) and a human-readable ``RESULTS.md`` — and copies the designed
binders into ``binders/`` for provenance. It does **no** GPU work; it just
aggregates real metrics that already exist.

    python benchmarks/designer_benchmark/score_run.py RUN.tar.gz \
        --designer rfdiff_mpnn --gpu "Tesla P100-16GB (Kaggle free)" \
        --target "ERBB2 domain IV (P04626, trastuzumab epitope)" \
        --out benchmarks/designer_benchmark
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import tarfile
from pathlib import Path

from bindsight import __version__
from bindsight.benchmark.designer_bench import (
    DEFAULT_IPTM_SUCCESS,
    DesignerScore,
    _render_md,
    _score_dict,
)


def _read_metrics(tar: Path) -> list[dict]:
    """Read metrics.jsonl rows from the results tarball."""
    with tarfile.open(tar, "r:gz") as tf:
        member = next((m for m in tf.getnames() if Path(m).name == "metrics.jsonl"), None)
        if member is None:
            raise SystemExit(f"{tar} has no metrics.jsonl")
        f = tf.extractfile(member)
        text = f.read().decode() if f else ""
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def _score(designer: str, rows: list[dict]) -> DesignerScore:
    """Aggregate validator rows into a DesignerScore (real, not mock)."""
    iptm = [r["iptm"] for r in rows if isinstance(r.get("iptm"), (int, float))]
    pae = [r["pae_interaction"] for r in rows if isinstance(r.get("pae_interaction"), (int, float))]
    aff = [
        r["affinity_pred_value"]
        for r in rows
        if isinstance(r.get("affinity_pred_value"), (int, float))
    ]
    s = DesignerScore(designer=designer, n_targets=1, n_designs=len(rows))
    if iptm:
        s.mean_iptm = round(statistics.fmean(iptm), 4)
        s.median_iptm = round(statistics.median(iptm), 4)
        s.success_rate = round(sum(v >= DEFAULT_IPTM_SUCCESS for v in iptm) / len(iptm), 4)
    if pae:
        s.mean_pae_interaction = round(statistics.fmean(pae), 4)
    if aff:
        s.mean_affinity = round(statistics.fmean(aff), 4)
    return s


def main() -> None:
    """Aggregate a results tarball into results.json + RESULTS.md and stage binders."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tarball", type=Path)
    ap.add_argument("--designer", default="rfdiff_mpnn")
    ap.add_argument("--validator", default="boltz2")
    ap.add_argument("--gpu", default="Tesla P100-16GB (Kaggle free)")
    ap.add_argument("--target", default="ERBB2 domain IV (P04626, trastuzumab epitope)")
    ap.add_argument("--n-trajectories", type=int, default=2)
    ap.add_argument("--out", type=Path, default=Path("benchmarks/designer_benchmark"))
    args = ap.parse_args()

    rows = _read_metrics(args.tarball)
    score = _score(args.designer, rows)
    summary = {
        "schema": "bindsight-designer-benchmark/1",
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "bindsight_version": __version__,
        "backend": "kaggle",
        "gpu": args.gpu,
        "validator": args.validator,
        "n_trajectories": args.n_trajectories,
        "is_mock": False,
        "targets": [args.target],
        "designers": [_score_dict(score)],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    md = _render_md(summary)
    md += (
        "\n## Run provenance\n\n"
        f"- **Real GPU run** — backend `kaggle`, GPU `{args.gpu}`, "
        f"date `{summary['generated_utc']}`, bindsight `{__version__}`.\n"
        f"- **Target:** {args.target}. The full ERBB2 (1255 aa) does not fit a free 16 GB "
        "GPU, so binders are designed against extracellular **domain IV** — the clinically "
        "validated trastuzumab epitope — extracted from the AlphaFold model "
        "(`prepare_erbb2_target.py`).\n"
        f"- **Pipeline:** RFdiffusion → ProteinMPNN → Boltz-2, run via the split-environment "
        "Kaggle kernel (`bindsight.runners.kaggle_kernel`).\n"
        "- **Metrics:** **ipTM** is the primary de novo binder-quality metric and "
        "**success@0.65** is the standard ipTM≥0.65 criterion. **PAE-interaction** is the mean "
        "inter-chain predicted aligned error (Å) from the Boltz-2 complex (lower = more confident "
        "interface). The **affinity column is intentionally blank** — Boltz-2 affinity prediction "
        "is ligand-only and these are protein binders.\n"
        f"- The real Boltz-2 **predicted complex structures** are staged in `binders/` as "
        "`<binder_id>_complex.cif` (the actual folded binder–target complex behind each ipTM), "
        "alongside the ProteinMPNN FASTAs, per-design `metrics.jsonl`, and `results.json`.\n"
    )
    (args.out / "RESULTS.md").write_text(md, encoding="utf-8")

    # Stage the ProteinMPNN FASTAs plus the real Boltz-2 *predicted complex* structures
    # (validate/<id>/*_model_0.cif) — the actual folded binder–target complex behind each
    # ipTM. The RFdiffusion poly-glycine backbone PDBs (design/*.pdb) are intentionally NOT
    # staged: they are a pre-sequence intermediate, and the predicted complex supersedes them.
    binders = args.out / "binders"
    binders.mkdir(parents=True, exist_ok=True)
    n_complexes = 0
    with tarfile.open(args.tarball, "r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = m.name
            is_design = name.startswith("design/") and name.endswith(".fasta")
            is_complex = name.startswith("validate/") and name.endswith((".cif", "_model_0.pdb"))
            if not (is_design or is_complex):
                continue
            data = tf.extractfile(m)
            if data is None:
                continue
            if is_complex:
                # validate/<binder_id>/<binder_id>_model_0.cif -> <binder_id>_complex.cif
                stem = Path(name).parent.name
                (binders / f"{stem}_complex.cif").write_bytes(data.read())
                n_complexes += 1
            else:
                (binders / Path(name).name).write_bytes(data.read())
    # Also keep the raw per-design metrics next to the binders.
    (binders / "metrics.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )

    print(
        f"wrote {args.out}/results.json + RESULTS.md; staged {len(rows)} designs "
        f"+ {n_complexes} predicted complex structure(s) into {binders}"
    )
    print(
        f"designs={score.n_designs} mean_ipTM={score.mean_iptm} success@0.65={score.success_rate}"
    )


if __name__ == "__main__":
    main()
