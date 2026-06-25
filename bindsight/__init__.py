# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bindsight — a reproducible bridge from RNA-seq to de novo protein binder design.

See https://github.com/mikhaeelatefrizk/bindsight for documentation.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bindsight")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
