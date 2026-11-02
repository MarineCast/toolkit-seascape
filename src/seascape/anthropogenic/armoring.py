"""Combine systematic armoring as the maximum available dataset estimate per cell."""

from __future__ import annotations

import math
from collections import defaultdict

from shapely import GeometryCollection, union_all


def dataset_estimates(records):
    """Measure each dataset on unique line locations within one cell.

    Within a dataset, coincident estimates use the largest fraction at that
    location. Disjoint line portions retain their length weights. Missing
    estimates never supply a zero or a surveyed denominator.
    """
    grouped = defaultdict(lambda: defaultdict(list))
    for geometry, fraction, dataset in records:
        if fraction is None or not math.isfinite(float(fraction)):
            continue
        fraction = float(fraction)
        if not 0 <= fraction <= 1 or not dataset:
            raise ValueError("Armoring requires a dataset and fractions in [0, 1]")
        if not geometry.is_empty and geometry.length > 0:
            grouped[str(dataset)][fraction].append(geometry)
    estimates = {}
    for dataset, fractions in sorted(grouped.items()):
        covered = GeometryCollection()
        weighted = 0.0
        for fraction, pieces in sorted(fractions.items(), reverse=True):
            geometry = union_all(pieces)
            weighted += fraction * geometry.difference(covered).length
            covered = union_all([covered, geometry])
        if covered.length > 0:
            estimates[dataset] = {
                "weighted_length_m": float(weighted),
                "surveyed_length_m": float(covered.length),
            }
    return estimates


def maximum_estimate(estimates):
    """Return the selected dataset's numerator, denominator and fraction."""
    candidates = []
    for dataset, values in sorted(estimates.items()):
        weighted, surveyed = (
            float(values["weighted_length_m"]),
            float(values["surveyed_length_m"]),
        )
        if not (
            math.isfinite(weighted)
            and math.isfinite(surveyed)
            and surveyed > 0
            and 0 <= weighted <= surveyed + 1e-8
        ):
            raise ValueError("Invalid per-dataset armoring lengths")
        candidates.append((min(1.0, weighted / surveyed), dataset, weighted, surveyed))
    if not candidates:
        return 0.0, 0.0, math.nan
    fraction, _dataset, weighted, surveyed = max(candidates)
    return weighted, surveyed, fraction


def combine_estimates(estimates):
    """Aggregate child support within each dataset before taking a parent maximum."""
    totals = {}
    for child in estimates:
        for dataset, values in child.items():
            row = totals.setdefault(
                dataset, {"weighted_length_m": 0.0, "surveyed_length_m": 0.0}
            )
            for name in row:
                row[name] += values[name]
    return totals
