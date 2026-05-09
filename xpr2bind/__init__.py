"""xpr2bind — a reproducible bridge from RNA-seq to de novo protein binder design.

See https://github.com/mikhaeelatefrizk/xpr2bind for documentation.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("xpr2bind")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
