"""Bounded finite-inventory Euclidean proximity; no physical flow inference."""

import numpy as np
from scipy.spatial.distance import cdist


def finite_inventory_metrics(target_xy, inventory_xy, tree, max_targets=512):
    target = np.asarray(target_xy, dtype=float)
    inventory = np.asarray(inventory_xy, dtype=float)
    if (
        target.ndim != 2
        or target.shape[1] != 2
        or inventory.ndim != 2
        or inventory.shape[1] != 2
    ):
        raise ValueError("Expected projected XY matrices")
    if not 0 < len(target) <= max_targets or max_targets > 512 or len(inventory) == 0:
        raise ValueError("Bounded nonempty batch/inventory required")
    if not np.isfinite(target).all() or not np.isfinite(inventory).all():
        raise ValueError("Finite projected coordinates required")
    distance, position = tree.query(target)
    kernel = cdist(target, inventory)
    kernel /= -5000.0
    np.exp(kernel, out=kernel)
    proximity = kernel.sum(axis=1)
    if (
        not np.isfinite(distance).all()
        or not np.isfinite(proximity).all()
        or (distance < 0).any()
        or (proximity < 0).any()
    ):
        raise ValueError("Nonfinite/negative finite-inventory result")
    return distance, position, proximity
