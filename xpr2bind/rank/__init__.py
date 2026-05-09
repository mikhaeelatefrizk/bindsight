"""Multi-objective ranking of validated binders.

Combines:

- Upstream evidence: DE log2FC × specificity penalty (vital-tissue baseline)
- Structure quality: iPTM, pAE_interaction, RMSD-to-designed
- Affinity: Boltz-2 ``affinity_pred_value`` and ``affinity_probability_binary``
- Sequence quality: ProteinMPNN sequence recovery vs. backbone

The rank module deliberately doesn't pick a single score for the user — it
emits a wide Parquet with all components and a configurable composite, so
users can resort by any metric in the Quarto/Streamlit report.
"""

from __future__ import annotations
