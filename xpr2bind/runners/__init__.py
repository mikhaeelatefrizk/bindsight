"""GPU-runner abstraction (Colab / Modal / Kaggle / local Docker / mock)."""

from xpr2bind.runners.protocol import CostEstimate, GPURunner, JobHandle, JobStatus

__all__ = ["CostEstimate", "GPURunner", "JobHandle", "JobStatus"]
