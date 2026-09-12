# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin loader — resolve designers / validators / runners by name.

Looks up the entry points declared in ``pyproject.toml``
(``bindsight.designers`` / ``bindsight.validators`` / ``bindsight.runners``) so
third parties can register their own without forking. Falls back to the bundled
import paths if the package metadata isn't available (editable corner cases).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

LOG = logging.getLogger(__name__)

_FALLBACK = {
    "bindsight.designers": {
        "rfdiff_mpnn": "bindsight.design.rfdiff_mpnn:RFdiffMPNNDesigner",
        "bindcraft": "bindsight.design.bindcraft:BindCraftDesigner",
        "boltzgen": "bindsight.design.boltzgen:BoltzGenDesigner",
    },
    "bindsight.validators": {
        "boltz2": "bindsight.validate.boltz2:Boltz2Validator",
        "chai1r": "bindsight.validate.chai1r:Chai1rValidator",
        "af2_ig": "bindsight.validate.af2_ig:AF2IGValidator",
    },
    "bindsight.runners": {
        "colab": "bindsight.runners.colab:ColabRunner",
        "modal": "bindsight.runners.modal_runner:ModalRunner",
        "kaggle": "bindsight.runners.kaggle:KaggleRunner",
        "local_docker": "bindsight.runners.local_docker:LocalDockerRunner",
        "mock": "bindsight.runners.mock:MockRunner",
    },
}


ALL_DESIGNERS: frozenset[str] = frozenset(_FALLBACK["bindsight.designers"])
ALL_VALIDATORS: frozenset[str] = frozenset(_FALLBACK["bindsight.validators"])
ALL_PLUGINS: frozenset[str] = ALL_DESIGNERS | ALL_VALIDATORS

SUPPORTED = "supported"
UNTESTED = "untested"
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class BackendCapability:
    """What one backend's environment can actually run.

    The distinction that matters is between *unsupported* and *untested*, and
    collapsing them would be its own kind of dishonesty.

    ``provides`` is what the backend builds an environment for. ``attempts`` is
    what :mod:`bindsight.runners.job_exec` would try to bootstrap at run time —
    it clones RFdiffusion, fetches and verifies its weights and pip-installs the
    SE3 stack, so a general-purpose CUDA image may well succeed without the
    backend having prepared anything. Nothing outside ``provides`` has been
    demonstrated, so an attempt is allowed and announced rather than blocked.

    Anything in neither set cannot run there at all, and asking for it should
    cost a second locally instead of six minutes of a weekly GPU quota.

    Attributes:
        provides: plugins this backend builds an environment for.
        attempts: plugins the executor would try to bootstrap, unproven.
        compute_capability: the card's CUDA compute capability, or None when the
            backend does not pin one.
        note: what a user needs to know when a combination is refused.
    """

    provides: frozenset[str]
    attempts: frozenset[str] = frozenset()
    compute_capability: tuple[int, int] | None = None
    note: str = ""


#: Minimum CUDA compute capability a plugin needs, with the reason.
#:
#: Chai-1r's bfloat16 assumption is spread through its modules rather than
#: sitting behind one argument, which is why the one-line precision patch that
#: makes Boltz-2 work on a T4 does not transfer to it.
PLUGIN_MIN_COMPUTE: dict[str, tuple[tuple[int, int], str]] = {
    "chai1r": ((8, 0), "requires bfloat16, which needs Ampere (sm_80) or newer"),
}


#: What each backend can run, stated from what its code actually builds.
#:
#: Kaggle is the sharp case. ``kaggle_kernel.build_kernel_script`` takes no
#: designer or validator argument at all and builds exactly two micromamba
#: environments — ``se3`` for RFdiffusion and ProteinMPNN, ``boltz`` for Boltz-2.
#: Asking it for BindCraft produced that same two-environment kernel, which
#: failed after roughly six minutes of environment building had already been
#: charged to the user's weekly quota.
BACKEND_CAPABILITIES: dict[str, BackendCapability] = {
    "kaggle": BackendCapability(
        provides=frozenset({"rfdiff_mpnn", "boltz2"}),
        compute_capability=(7, 5),
        note=(
            "the Kaggle kernel builds exactly two environments, se3 "
            "(RFdiffusion + ProteinMPNN) and boltz (Boltz-2), and nothing "
            "selects a different one"
        ),
    ),
    "colab": BackendCapability(
        provides=frozenset({"rfdiff_mpnn", "boltz2"}),
        compute_capability=(7, 5),
        note="the generated notebook installs RFdiffusion, ProteinMPNN and Boltz-2 only",
    ),
    "modal": BackendCapability(
        provides=frozenset({"boltz2"}),
        attempts=frozenset({"rfdiff_mpnn"}),
        note=(
            "the Modal image installs Boltz-2 on a CUDA devel base; the executor "
            "would bootstrap RFdiffusion itself, which has not been run"
        ),
    ),
    "local_docker": BackendCapability(
        provides=frozenset({"boltz2"}),
        attempts=frozenset({"rfdiff_mpnn"}),
        note=(
            "the image ships Boltz-2; the executor would bootstrap RFdiffusion "
            "itself, which the CPU tests do not exercise"
        ),
    ),
    # The mock backend synthesises results and runs no tool, so every name is
    # accepted. That is what makes it useful for testing orchestration and
    # useless as evidence, which its own output says on every row.
    "mock": BackendCapability(provides=ALL_PLUGINS, note="synthetic results; runs no tool"),
}


def plugin_support(backend: str, plugin: str) -> tuple[str, str]:
    """Whether ``backend`` can run ``plugin``, and why.

    Args:
        backend: runner name.
        plugin: designer or validator name.

    Returns:
        ``(SUPPORTED | UNTESTED | UNSUPPORTED, explanation)``. An unknown
        backend is treated as untested rather than refused, so a third-party
        runner registered through the entry points is never blocked by a table
        it could not have been added to.
    """
    capability = BACKEND_CAPABILITIES.get(backend)
    if capability is None:
        return UNTESTED, f"{backend!r} is not a bundled backend, so its environment is unknown"

    required = PLUGIN_MIN_COMPUTE.get(plugin)
    if (
        required is not None
        and capability.compute_capability is not None
        and capability.compute_capability < required[0]
    ):
        major, minor = required[0]
        have = ".".join(str(n) for n in capability.compute_capability)
        return UNSUPPORTED, (
            f"{plugin} {required[1]}; {backend} pins a card at compute capability "
            f"{have}, below sm_{major}{minor}"
        )

    if plugin in capability.provides:
        return SUPPORTED, ""
    if plugin in capability.attempts:
        return UNTESTED, (
            f"{backend} has no prepared environment for {plugin}; the executor "
            f"would try to bootstrap it, which has not been run end to end"
        )
    return UNSUPPORTED, (
        f"{backend} cannot run {plugin}: {capability.note}. "
        f"It provides: {', '.join(sorted(capability.provides))}"
    )


def _load(group: str, name: str) -> type:
    """Resolve a plugin class by entry-point group + name."""
    try:
        eps = entry_points(group=group)
        for ep in eps:
            if ep.name == name:
                return ep.load()  # type: ignore[no-any-return]
    except Exception:  # pragma: no cover - metadata edge cases
        pass
    # Fallback: import the bundled path directly.
    target = _FALLBACK.get(group, {}).get(name)
    if target is None:
        raise ValueError(f"unknown {group} plugin: {name!r}")
    module_path, _, cls_name = target.partition(":")
    import importlib

    return getattr(importlib.import_module(module_path), cls_name)  # type: ignore[no-any-return]


def get_designer(name: str) -> Any:
    """Instantiate a designer plugin by name."""
    return _load("bindsight.designers", name)()


#: Constructor kwargs whose silent loss changes what a result means.
#:
#: Dropping ``gpu_type`` costs an accurate cost estimate. Dropping
#: ``bindsight_wheel`` means the GPU installs the repository's default branch
#: instead of the code in front of you, and the run's own summary went on
#: reporting "working-tree wheel ..." because it described what was *asked for*
#: rather than what the runner took. That is the failure the wheel exists to
#: prevent, so losing it has to be loud.
_PROVENANCE_KWARGS = frozenset({"bindsight_wheel", "bindsight_ref"})


def runner_accepts(name: str, param: str) -> bool:
    """Whether backend ``name``'s constructor takes ``param``.

    Callers that *report* on a kwarg need this, because passing one to
    :func:`get_runner` is not the same as the runner using it.

    Args:
        name: the runner's entry-point name.
        param: the constructor parameter to look for.

    Returns:
        True when the runner accepts it.
    """
    import inspect

    return param in inspect.signature(_load("bindsight.runners", name)).parameters


def get_runner(name: str, **kwargs: Any) -> Any:
    """Instantiate a runner backend by name.

    Runners have heterogeneous constructors (e.g. ``MockRunner`` takes none of
    the design kwargs), so only the kwargs a given runner actually accepts are
    forwarded. Anything dropped that changes what a result *means* is logged
    rather than discarded quietly: ``ModalRunner`` takes no ``bindsight_wheel``,
    so a benchmark that built one from the working tree had it silently
    thrown away and the GPU installed the default branch, while the published
    summary still named the wheel.
    """
    import inspect

    cls = _load("bindsight.runners", name)
    params = inspect.signature(cls).parameters
    accepted = {k: v for k, v in kwargs.items() if k in params}

    dropped = sorted(k for k in kwargs if k not in params and kwargs[k] is not None)
    for key in dropped:
        if key in _PROVENANCE_KWARGS:
            LOG.warning(
                "backend %r does not accept %s, so it was discarded: the remote job "
                "will install bindsight from its own default source, not from the "
                "code that launched it. Results from this run cannot be attributed "
                "to this working tree.",
                name,
                key,
            )
        else:
            LOG.debug("backend %r does not accept %s; ignored", name, key)
    return cls(**accepted)
