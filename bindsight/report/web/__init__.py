# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bindsight web interface.

Server-rendered HTML over the same data layer the standalone report reads
(:mod:`bindsight.report.showcase`), with one stylesheet shared between them so
the interactive app and the file a collaborator opens from an email look like
the same instrument.

Replaces the Streamlit app. That is a reduction, not an addition: Streamlit
declares 34 requirements against this stack's handful, and every number on a
Streamlit page had to be expressed through a widget whose layout the caller does
not control -- which is how confidence intervals ended up inside hover tooltips
underneath a paragraph promising every rate carried its interval.

Nothing here needs a build step, a package manager, or a network. The one
third-party asset is 3Dmol.js, vendored under ``static/vendor/`` so the
structure viewer works offline; the previous viewer fetched it from a CDN, so it
silently required internet.
"""

from __future__ import annotations

__all__ = ["create_app", "serve"]


def __getattr__(name: str) -> object:
    # Imported lazily so ``import bindsight.report`` does not require the web
    # extra. ``bindsight doctor`` and the CLI's non-UI paths must work on an
    # install that never asked for a server.
    if name in __all__:
        from bindsight.report.web.app import create_app, serve

        return {"create_app": create_app, "serve": serve}[name]
    raise AttributeError(name)
