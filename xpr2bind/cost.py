"""GPU cost estimator.

Powers ``xpr2bind design --dry-run`` and ``xpr2bind run --dry-run``. Returns
a :class:`xpr2bind.runners.CostEstimate` for any (backend, designer/validator,
spec_size) tuple WITHOUT launching anything.

The pricing tables here are conservative point-in-time values (see
:data:`PRICE_TABLE_VERSION`). They are NOT a quote — actual cloud pricing
varies with region, spot vs on-demand, and provider promotions. The cost
shown by ``--dry-run`` is an order-of-magnitude estimate to help users
decide whether to proceed, not an invoice.

To update prices: bump :data:`PRICE_TABLE_VERSION` and edit
:data:`GPU_PRICE_USD_PER_HOUR`. Tests pin specific values and will catch
unintended drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from xpr2bind.runners.protocol import CostEstimate

# Bumped any time the pricing or timing tables change.
PRICE_TABLE_VERSION = "2026.05"


# ---------------------------------------------------------------------------
# Pricing — USD per GPU-hour, on-demand list price as of PRICE_TABLE_VERSION
# ---------------------------------------------------------------------------
# Free-tier providers map to 0.0; users still pay in queue time and quota.
GPU_PRICE_USD_PER_HOUR: dict[tuple[str, str], float] = {
    # backend, gpu_type           USD/hr
    ("modal", "T4"): 0.59,
    ("modal", "L4"): 0.75,
    ("modal", "A10G"): 1.10,
    ("modal", "A100-40GB"): 3.09,
    ("modal", "A100-80GB"): 3.50,
    ("modal", "H100"): 4.56,
    ("colab", "T4"): 0.00,  # Colab free
    ("colab", "A100-40GB"): 1.40,  # Colab Pro+ compute units, amortized
    ("kaggle", "T4"): 0.00,  # Kaggle free
    ("kaggle", "P100"): 0.00,
    ("local_docker", "T4"): 0.00,
    ("local_docker", "A100-40GB"): 0.00,
    ("local_docker", "RTX4090"): 0.00,
    ("mock", "mock"): 0.00,
}


# ---------------------------------------------------------------------------
# Per-designer / per-validator GPU-time estimates
# ---------------------------------------------------------------------------
# Time PER trajectory or PER design, in seconds, on a reference GPU.
# These are rough estimates from the upstream papers + community reports.
# Sources noted inline so we can revise when better data lands.


@dataclass(frozen=True)
class _Timing:
    seconds_per_unit: float
    reference_gpu: str
    notes: str


_DESIGNER_TIMING: dict[str, _Timing] = {
    # RFdiffusion + ProteinMPNN: backbone diffusion ~30s, sequence design ~2s/seq.
    # We bundle them into one trajectory unit for simplicity.
    "rfdiff_mpnn": _Timing(
        seconds_per_unit=45.0,
        reference_gpu="A100-40GB",
        notes="RFdiffusion ~30s + ProteinMPNN ~2s/seq, on A100. Free Colab T4 takes ~3-5x longer.",
    ),
    # BindCraft: published ~3-5 min/trajectory on A100, requires >=32GB VRAM.
    "bindcraft": _Timing(
        seconds_per_unit=240.0,
        reference_gpu="A100-40GB",
        notes="BindCraft Nature 2025 paper reports ~3-5 min/trajectory on A100. Needs >=32GB VRAM.",
    ),
    # BoltzGen: similar order to RFdiff+MPNN, slightly faster per unit.
    "boltzgen": _Timing(
        seconds_per_unit=40.0,
        reference_gpu="A100-40GB",
        notes="BoltzGen 2025 release. Approximate; will refine after benchmark in v0.2 paper.",
    ),
}


_VALIDATOR_TIMING: dict[str, _Timing] = {
    "boltz2": _Timing(
        seconds_per_unit=20.0,
        reference_gpu="A100-40GB",
        notes="Boltz-2 README claims ~seconds-minutes per complex on A100. 20s/design conservative.",
    ),
    "chai1r": _Timing(
        seconds_per_unit=25.0,
        reference_gpu="A100-40GB",
        notes="Chai-1r similar to Boltz-2 in scale.",
    ),
    "af2_ig": _Timing(
        seconds_per_unit=120.0,
        reference_gpu="A100-40GB",
        notes="AF2 with initial guess is slower than single-step models.",
    ),
}


# Approximate scaling factor when running on a slower GPU than the reference.
# Applied multiplicatively to the per-unit time.
_GPU_SLOWDOWN: dict[str, float] = {
    "T4": 4.0,
    "L4": 2.5,
    "A10G": 2.0,
    "P100": 3.0,
    "A100-40GB": 1.0,
    "A100-80GB": 1.0,
    "H100": 0.6,
    "RTX4090": 1.5,
    "mock": 0.0,
}


# Default GPU per backend if the user doesn't specify one.
_DEFAULT_GPU: dict[str, str] = {
    "modal": "A100-40GB",
    "colab": "T4",  # free tier
    "kaggle": "T4",
    "local_docker": "A100-40GB",  # arbitrary; user knows their hardware
    "mock": "mock",
}


# Approximate queue waits in minutes (free tiers are queue-prone).
_QUEUE_WAIT_MIN: dict[str, float] = {
    "modal": 0.5,  # cold start
    "colab": 2.0,  # free tier; Pro is faster
    "kaggle": 3.0,  # free tier
    "local_docker": 0.0,
    "mock": 0.0,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
StageKind = Literal["design", "validate"]


def estimate(
    *,
    backend: str,
    stage: StageKind,
    plugin: str,
    n_units: int,
    gpu_type: str | None = None,
) -> CostEstimate:
    """Estimate GPU cost for a stage.

    Args:
        backend: ``"colab"`` | ``"modal"`` | ``"kaggle"`` | ``"local_docker"`` | ``"mock"``.
        stage: ``"design"`` (cost per design trajectory) or ``"validate"``
            (cost per design validated).
        plugin: designer or validator name (e.g. ``"rfdiff_mpnn"``, ``"boltz2"``).
        n_units: number of trajectories (design) or designs (validate).
        gpu_type: override the default GPU for the backend.

    Raises:
        ValueError: if ``backend``/``plugin``/``gpu_type`` is unknown.

    Returns:
        A :class:`CostEstimate` with the projected GPU-hours and USD.
    """
    if backend not in _DEFAULT_GPU:
        raise ValueError(f"unknown backend: {backend}")

    chosen_gpu = gpu_type or _DEFAULT_GPU[backend]
    if chosen_gpu not in _GPU_SLOWDOWN:
        raise ValueError(f"unknown GPU type: {chosen_gpu}. Known: {sorted(_GPU_SLOWDOWN)}")

    timing_table = _DESIGNER_TIMING if stage == "design" else _VALIDATOR_TIMING
    if plugin not in timing_table:
        raise ValueError(f"unknown {stage} plugin: {plugin}. Known: {sorted(timing_table)}")
    timing = timing_table[plugin]

    if chosen_gpu == "mock":
        seconds = 0.0
    else:
        slowdown = _GPU_SLOWDOWN[chosen_gpu]
        seconds = timing.seconds_per_unit * slowdown * n_units

    gpu_hours = seconds / 3600.0
    price_per_hour = GPU_PRICE_USD_PER_HOUR.get((backend, chosen_gpu))
    if price_per_hour is None:
        raise ValueError(
            f"no price entry for ({backend}, {chosen_gpu}) in PRICE_TABLE_VERSION={PRICE_TABLE_VERSION}"
        )
    usd = round(gpu_hours * price_per_hour, 2)
    queue = _QUEUE_WAIT_MIN.get(backend, 0.0)

    return CostEstimate(
        backend=backend,
        gpu_type=chosen_gpu,
        gpu_hours=round(gpu_hours, 3),
        usd_estimate=usd if price_per_hour > 0 else 0.0,
        queue_minutes_estimate=queue,
        notes=(
            f"{plugin}: {timing.seconds_per_unit:.0f}s/unit on {timing.reference_gpu} "
            f"× slowdown={_GPU_SLOWDOWN[chosen_gpu]:.1f} × n={n_units}. "
            f"Pricing table {PRICE_TABLE_VERSION}. {timing.notes}"
        ),
    )


def estimate_full_run(
    *,
    backend: str,
    designer: str,
    validator: str,
    n_targets: int,
    n_trajectories: int,
    gpu_type: str | None = None,
) -> tuple[CostEstimate, CostEstimate, CostEstimate]:
    """Estimate cost for a full design + validate pass.

    Returns ``(design_cost, validate_cost, combined_cost)``.
    """
    n_design_units = n_targets * n_trajectories
    n_validate_units = n_design_units  # validate one structure per design

    d = estimate(
        backend=backend,
        stage="design",
        plugin=designer,
        n_units=n_design_units,
        gpu_type=gpu_type,
    )
    v = estimate(
        backend=backend,
        stage="validate",
        plugin=validator,
        n_units=n_validate_units,
        gpu_type=gpu_type,
    )
    combined = CostEstimate(
        backend=backend,
        gpu_type=d.gpu_type,
        gpu_hours=round(d.gpu_hours + v.gpu_hours, 3),
        usd_estimate=round((d.usd_estimate or 0.0) + (v.usd_estimate or 0.0), 2),
        queue_minutes_estimate=d.queue_minutes_estimate,
        notes=(
            f"combined: design ({n_design_units} units of {designer}) + "
            f"validate ({n_validate_units} units of {validator})"
        ),
    )
    return d, v, combined
