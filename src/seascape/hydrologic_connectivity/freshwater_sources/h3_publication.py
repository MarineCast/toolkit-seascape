"""H3 feature calculations owned by freshwater-source publication."""

from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist

PRESSURE_DISTANCE_CHUNK_SIZE = 512


def river_mouth_pressure(
    target_xy: np.ndarray,
    mouth_xy: np.ndarray,
    mouth_width_m: np.ndarray,
    *,
    decay_distance_m: float,
    width_reference_m: float,
    chunk_size: int = PRESSURE_DISTANCE_CHUNK_SIZE,
) -> tuple[np.ndarray, np.ndarray]:
    """Calculate exact unweighted and square-root-width-weighted mouth pressure."""

    if target_xy.ndim != 2 or target_xy.shape[1] != 2:
        raise ValueError("River-mouth pressure targets must have shape (n, 2).")
    if mouth_xy.ndim != 2 or mouth_xy.shape[1] != 2 or len(mouth_xy) == 0:
        raise ValueError("River-mouth pressure sources must have nonempty shape (n, 2).")
    widths = np.asarray(mouth_width_m, dtype="float64")
    if widths.shape != (len(mouth_xy),) or not np.isfinite(widths).all():
        raise ValueError("River-mouth pressure widths must be finite and align to mouths.")
    if decay_distance_m <= 0 or width_reference_m <= 0 or chunk_size <= 0:
        raise ValueError(
            "River-mouth pressure distance, width reference, and chunk must be positive."
        )
    unweighted = np.empty(len(target_xy), dtype="float64")
    width_weighted = np.empty(len(target_xy), dtype="float64")
    width_weights = np.sqrt(widths / width_reference_m)
    for start in range(0, len(target_xy), chunk_size):
        stop = min(start + chunk_size, len(target_xy))
        kernel = np.exp(-cdist(target_xy[start:stop], mouth_xy) / decay_distance_m)
        unweighted[start:stop] = kernel.sum(axis=1)
        width_weighted[start:stop] = kernel @ width_weights
    return unweighted, width_weighted


__all__ = ["river_mouth_pressure"]
