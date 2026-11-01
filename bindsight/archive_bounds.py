# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resource bounds applied before tarfile parses untrusted gzip/tar archives.

These guards do not authorize extraction: callers must still check member paths,
types, logical sizes, destinations, and the total bytes they actually extract.
"""

from __future__ import annotations

import gzip
import os
import tarfile
import tempfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import IO, Any, cast

MAX_EXTENSION_BYTES = 1024 * 1024
MAX_TOTAL_METADATA_BYTES = 16 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_SPOOL_MEMORY_BYTES = 1024 * 1024


class ArchiveLimitError(tarfile.ReadError):
    """An archive exceeds a bound before its metadata or payload is allocated."""


@contextmanager
def open_bounded_tar(
    path: str | os.PathLike[str] | IO[bytes],
    *,
    max_bytes: int,
    max_members: int,
    encoding: str = "utf-8",
) -> Iterator[tarfile.TarFile]:
    """Yield a seekable read-only TarFile with bounded decoding and metadata.

    ``max_bytes`` is the caller's payload allowance. The decoded spool additionally
    permits at most min(16 MiB, max_bytes) extension bytes, 1024 bytes per physical
    header for headers/padding, and one 10240-byte end record. All physical headers
    count against ``max_members``, including PAX and GNU longname/link headers.
    Each extension is capped at min(1 MiB, max_bytes) before the stdlib parser reads
    it. gzip and uncompressed tar are supported; extraction policy is caller-owned.
    Caller-owned streams stay open and their original position is restored.
    """
    if max_bytes <= 0 or max_members <= 0:
        raise ValueError("Archive budgets must be positive")
    metadata_budget = min(MAX_TOTAL_METADATA_BYTES, max_bytes)
    extension_budget = min(MAX_EXTENSION_BYTES, max_bytes)
    decoded_budget = max_bytes + metadata_budget + max_members * 1024 + 10240
    limit_message = "Archive exceeds size or member limit"
    counts = {"headers": 0, "metadata": 0}

    class BoundedTarInfo(tarfile.TarInfo):
        def _proc_member(self, archive: Any) -> Any:
            # _proc_member is called for physical headers, including the nested
            # headers fetched by PAX/GNU parsing in supported Python 3.11â€“3.13.
            counts["headers"] += 1
            if counts["headers"] > max_members:
                raise ArchiveLimitError(limit_message)
            if self.type in {
                tarfile.XHDTYPE,
                tarfile.XGLTYPE,
                tarfile.SOLARIS_XHDTYPE,
                tarfile.GNUTYPE_LONGNAME,
                tarfile.GNUTYPE_LONGLINK,
            }:
                counts["metadata"] += self.size
                if (
                    self.size < 0
                    or self.size > extension_budget
                    or counts["metadata"] > metadata_budget
                ):
                    raise ArchiveLimitError(limit_message)
            result = super()._proc_member(archive)  # type: ignore[misc]
            # PAX may replace the raw size only after a nested header is read.
            # Check the returned logical member as well, without reimplementing
            # its offsets or allowing an oversized extractfile(...).read().
            if result.size < 0 or result.size > max_bytes:
                raise ArchiveLimitError(limit_message)
            return result

        def _proc_sparse(self, archive: Any) -> Any:
            # Scientific result/MSA readers already reject sparse files. Reject
            # before the legacy parser can accumulate unbounded sparse maps.
            raise tarfile.ReadError("Sparse tar metadata is unsupported")

        def _proc_gnusparse_00(self, *args: Any) -> Any:
            raise tarfile.ReadError("Sparse tar metadata is unsupported")

        def _proc_gnusparse_01(self, *args: Any) -> Any:
            raise tarfile.ReadError("Sparse tar metadata is unsupported")

        def _proc_gnusparse_10(self, *args: Any) -> Any:
            raise tarfile.ReadError("Sparse tar metadata is unsupported")

    owns_source = not hasattr(path, "read")
    with (
        open(cast("str | os.PathLike[str]", path), "rb")
        if owns_source
        else nullcontext(cast("IO[bytes]", path))
    ) as source:
        original_position = source.tell()
        try:
            source.seek(0, os.SEEK_END)
            compressed_bytes = source.tell() - original_position
            source.seek(original_position)
            if not 0 < compressed_bytes <= decoded_budget:
                raise ArchiveLimitError(limit_message)
            magic = source.read(2)
            source.seek(original_position)
            decoded: Any = (
                gzip.GzipFile(fileobj=source, mode="rb") if magic == b"\x1f\x8b" else source
            )
            try:
                with tempfile.SpooledTemporaryFile(
                    max_size=_SPOOL_MEMORY_BYTES, mode="w+b"
                ) as spool:
                    size = 0
                    try:
                        while block := decoded.read(min(_CHUNK_BYTES, decoded_budget - size + 1)):
                            size += len(block)
                            if size > decoded_budget:
                                raise ArchiveLimitError(limit_message)
                            spool.write(block)
                    except (OSError, EOFError, zlib.error) as error:
                        raise tarfile.ReadError("Cannot decode bounded tar archive") from error
                    spool.seek(0)
                    # The input is now a bounded, decoded seekable spool. Retaining
                    # tarfile's parser preserves PAX logical-size/offset semantics.
                    with tarfile.open(
                        fileobj=spool, mode="r:", encoding=encoding, tarinfo=BoundedTarInfo
                    ) as archive:
                        yield archive
            finally:
                if decoded is not source:
                    decoded.close()
        finally:
            if not owns_source:
                source.seek(original_position)
