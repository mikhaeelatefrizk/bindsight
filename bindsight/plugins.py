# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin loader — resolve designers / validators / runners by name.

Looks up the entry points declared in ``pyproject.toml``
(``bindsight.designers`` / ``bindsight.validators`` / ``bindsight.runners``) so
third parties can register their own without forking. Falls back to the bundled
import paths if the package metadata isn't available (editable corner cases).
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

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


def get_validator(name: str) -> Any:
    """Instantiate a validator plugin by name."""
    return _load("bindsight.validators", name)()


def get_runner(name: str, **kwargs: Any) -> Any:
    """Instantiate a runner backend by name.

    Runners have heterogeneous constructors (e.g. ``MockRunner`` takes none of
    the design kwargs), so only the kwargs a given runner actually accepts are
    forwarded.
    """
    import inspect

    cls = _load("bindsight.runners", name)
    params = inspect.signature(cls).parameters
    accepted = {k: v for k, v in kwargs.items() if k in params}
    return cls(**accepted)
