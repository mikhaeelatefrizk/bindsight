# SPDX-License-Identifier: AGPL-3.0-or-later
"""Distinguish unassessed annotations from measured biological exclusions."""

from typing import Any


def annotation_coverage(taxonomy: Any) -> dict[str, Any]:
    """Summarise actual failure dispositions without counting intentional caps as outages."""
    if taxonomy is None:
        return {"available": False, "unassessed_lookups": None, "dispositions": {}}
    if taxonomy.empty:
        return {"available": True, "unassessed_lookups": 0, "dispositions": {}}
    dispositions = taxonomy["disposition"].fillna("").astype(str)
    missing = dispositions.str.endswith(("_unassessed", "_lookup_failed"))
    if "open_targets_status" in taxonomy:
        statuses = taxonomy["open_targets_status"].fillna("").astype(str)
        missing |= statuses.str.startswith("error:")
    return {
        "available": True,
        "unassessed_lookups": int(missing.sum()),
        "dispositions": {str(k): int(v) for k, v in dispositions[missing].value_counts().items()},
        "intentionally_beyond_enrichment_cap": int(
            (dispositions == "below_enrichment_cutoff").sum()
        ),
        "structure_not_queried": int((dispositions == "structure_not_queried").sum()),
    }
