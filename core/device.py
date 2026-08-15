"""Shared CUDA/CPU device resolution — used by training, evaluation, export and inference."""
from __future__ import annotations


def resolve_device(requested: str = "auto") -> str:
    """'auto' -> '0' if a CUDA GPU is available, else 'cpu'. Never raises."""
    if requested != "auto":
        return requested
    try:
        import torch
        return "0" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"
