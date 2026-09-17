# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cache key must cover everything the remote executor acts on.

`_RESULT_AFFECTING_PARAMS` is a hand-written tuple, and a hand-written list of
things stops covering them the moment someone adds one. That has now happened
three times in this file's history, each time the same way and each time with
the same consequence -- two jobs that are different work sharing a key, so the
second silently returns the first's numbers under the second's label:

* `validator` was missing, so a run validated by Boltz-2 and a run validated by
  Chai-1r shared an entry.
* `designer` and `designer_version` were missing; the three adapters happened
  not to collide only because each passes a distinct pinned commit through
  `extra=`, which is incidental to the field that chooses the tool.
* `boltzgen_protocol` and `boltzgen_use_kernels` were missing, so two BoltzGen
  jobs running different design protocols shared an entry.

A wrong cached answer is the worst failure mode this project has, because it
looks entirely plausible: the manifest records the parameters that were asked
for, and the numbers underneath came from different ones.

So the tuple is no longer trusted to be complete. This derives the set of
`extra_params` keys `job_exec` actually reads, and requires each to be either
keyed or explicitly exempt with a documented reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

from bindsight.design._common import _CACHE_KEY_EXEMPT_PARAMS, _RESULT_AFFECTING_PARAMS

JOB_EXEC = Path(__file__).resolve().parents[1] / "bindsight" / "runners" / "job_exec.py"


def _params_the_executor_reads() -> set[str]:
    """Every literal key fetched from an ``extra_params`` mapping in job_exec.

    Matches both shapes the file uses: `spec.get("extra_params", {}).get("x")`
    and the rebound `extra = spec.get("extra_params", {})` followed by
    `extra.get("x")`. Walking the AST rather than the text so a key inside a
    comment or a docstring cannot satisfy it.
    """
    tree = ast.parse(JOB_EXEC.read_text(encoding="utf-8"))

    # Names bound to an extra_params mapping, so `extra.get("x")` counts.
    aliases = {"extra_params"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and "extra_params" in ast.dump(node.value):
            aliases.add(target.id)

    found: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "get" or not node.args:
            continue
        key = node.args[0]
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        recv = node.func.value
        reads_extra_params = (
            isinstance(recv, ast.Name) and recv.id in aliases
        ) or "extra_params" in ast.dump(recv)
        if reads_extra_params and key.value != "extra_params":
            found.add(key.value)
    return found


class TestTheCacheKeyCoversWhatTheExecutorActsOn:
    def test_the_scan_finds_something(self) -> None:
        """Without this, a scan that silently matched nothing would pass below."""
        found = _params_the_executor_reads()

        assert len(found) >= 5, f"the AST scan found only {sorted(found)}; it has stopped working"
        assert "validator" in found, "the scan missed a key the file demonstrably reads"

    def test_every_key_the_executor_reads_is_keyed_or_exempt(self) -> None:
        unaccounted = (
            _params_the_executor_reads()
            - set(_RESULT_AFFECTING_PARAMS)
            - set(_CACHE_KEY_EXEMPT_PARAMS)
        )

        assert not unaccounted, (
            f"job_exec acts on {sorted(unaccounted)}, which neither enters the cache key "
            "nor is listed in _CACHE_KEY_EXEMPT_PARAMS. Two jobs differing only in one "
            "of these share a key, so the second returns the first's results. Add it to "
            "_RESULT_AFFECTING_PARAMS, or exempt it with the reason why it cannot "
            "change the result."
        )

    def test_nothing_is_exempt_that_the_executor_never_reads(self) -> None:
        """An exemption for a key nobody reads is a stale note that hides the next one."""
        stale = set(_CACHE_KEY_EXEMPT_PARAMS) - _params_the_executor_reads()

        assert not stale, f"exempted but never read by job_exec: {sorted(stale)}"

    def test_the_boltzgen_parameters_are_in_the_key(self) -> None:
        """The specific regression: named, so the fix cannot be quietly undone."""
        assert "boltzgen_protocol" in _RESULT_AFFECTING_PARAMS
        assert "boltzgen_use_kernels" in _RESULT_AFFECTING_PARAMS


class TestTwoJobsDifferingOnlyInProtocolGetDifferentKeys:
    """The behaviour, not just the tuple's contents."""

    @staticmethod
    def _spec(**extra: object):
        from bindsight.design.protocol import DesignSpec

        return DesignSpec(
            target_uniprot="P04626",
            target_structure_path="missing.pdb",
            epitope_chain="A",
            epitope_residues=[1, 2, 3],
            design_ranges=[],
            n_trajectories=4,
            seed=0,
            binder_length_min=50,
            binder_length_max=60,
            extra_params={"designer": "boltzgen", "designer_version": "0.1.0", **extra},
        )

    def test_a_different_protocol_is_different_work(self) -> None:
        from bindsight.design._common import make_cache_key

        a = make_cache_key(self._spec(boltzgen_protocol="protein-anything"))
        b = make_cache_key(self._spec(boltzgen_protocol="protein-protein"))

        assert a != b

    def test_a_different_kernel_path_is_different_work(self) -> None:
        from bindsight.design._common import make_cache_key

        a = make_cache_key(self._spec(boltzgen_use_kernels="auto"))
        b = make_cache_key(self._spec(boltzgen_use_kernels="off"))

        assert a != b

    def test_identical_specs_still_share_a_key(self) -> None:
        """The point of a cache: this must stay true."""
        from bindsight.design._common import make_cache_key

        assert make_cache_key(self._spec(boltzgen_protocol="p")) == make_cache_key(
            self._spec(boltzgen_protocol="p")
        )


class TestThePayloadDigestIsTheSameOnEveryPlatform:
    """`_with_payload` ordered its files by sorting `Path` objects.

    `PurePath.__lt__` compares the parts tuple, and folds case on Windows. So a
    payload holding `a.txt`, `a/b.txt` and `B.txt` was hashed in the order
    `["B.txt", "a/b.txt", "a.txt"]` on Linux and `["a/b.txt", "a.txt", "B.txt"]`
    on Windows, and the same bytes produced two different keys.

    The key is supposed to be the identity of the content. One that changes with
    the operating system is not: a rerun on CI could not reuse a result computed
    locally, and two keys that differed asserted the payloads differed when they
    did not.
    """

    @staticmethod
    def _payload(root: Path) -> Path:
        payload = root / "design"
        (payload / "a").mkdir(parents=True)
        (payload / "a.txt").write_bytes(b"one")
        (payload / "a" / "b.txt").write_bytes(b"two")
        (payload / "B.txt").write_bytes(b"three")
        return payload

    def test_the_order_is_the_posix_path_string_not_the_path_object(self, tmp_path: Path) -> None:
        import hashlib

        from bindsight.design._common import _with_payload

        payload = self._payload(tmp_path)

        # What the implementation must produce: files in POSIX-string order.
        expected = hashlib.sha256()
        for rel in sorted(["a.txt", "a/b.txt", "B.txt"]):
            expected.update(rel.encode())
            expected.update(b"\0")
            expected.update(hashlib.sha256((payload / rel).read_bytes()).digest())
        want = hashlib.sha256(f"k|payload={expected.hexdigest()}".encode()).hexdigest()

        assert _with_payload("k", payload) == want

    def test_the_two_platform_orderings_are_genuinely_different(self) -> None:
        """Without this the test above could pass on a tie and prove nothing."""
        import pathlib

        names = ["a.txt", "a/b.txt", "B.txt"]
        posix = [p.as_posix() for p in sorted(pathlib.PurePosixPath(n) for n in names)]
        windows = [p.as_posix() for p in sorted(pathlib.PureWindowsPath(n) for n in names)]

        assert posix != windows, "the fixture no longer distinguishes the two orderings"
        assert sorted(names) not in (posix, windows), (
            "the string order coincides with a Path order; the fixture proves nothing"
        )

    def test_renaming_a_file_still_changes_the_key(self, tmp_path: Path) -> None:
        """The property the fold exists for must survive the ordering change."""
        from bindsight.design._common import _with_payload

        before = _with_payload("k", self._payload(tmp_path))
        (tmp_path / "design" / "a.txt").rename(tmp_path / "design" / "z.txt")

        assert _with_payload("k", tmp_path / "design") != before

    def test_identical_payloads_still_agree(self, tmp_path: Path) -> None:
        from bindsight.design._common import _with_payload

        one = _with_payload("k", self._payload(tmp_path / "one"))
        two = _with_payload("k", self._payload(tmp_path / "two"))

        assert one == two
