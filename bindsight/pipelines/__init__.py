# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end pipeline orchestrators.

Each module here exposes a ``run(config: RunConfig, ...) -> Manifest``
function that drives a chunk of the pipeline. The Click CLI calls these
directly (and the Snakefile calls them via ``scripts/``), so behavior stays
identical regardless of how a user invokes a stage.
"""
