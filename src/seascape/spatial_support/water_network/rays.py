"""Bounded vectorized evaluation of the unchanged 100 m sampled-ray rule."""

import math

import numpy as np
from shapely import covers, linestrings, points, prepare

from .geometry import GEOD


def directional_distances(longitudes, latitudes, maximum_m, water, *, cell_chunk=32):
    longitudes = np.asarray(longitudes, dtype=float)
    latitudes = np.asarray(latitudes, dtype=float)
    if longitudes.ndim != 1 or latitudes.shape != longitudes.shape:
        raise ValueError("Ray coordinates must be aligned one-dimensional arrays")
    if not np.isfinite(maximum_m) or maximum_m <= 0 or cell_chunk < 1:
        raise ValueError("Ray range and chunk size must be positive")
    if not np.isfinite(longitudes).all() or not np.isfinite(latitudes).all():
        raise ValueError("Ray coordinates must be finite")
    bearings = np.linspace(0.0, 360.0, 16, endpoint=False)
    distances = np.linspace(
        0.0, float(maximum_m), max(2, int(math.ceil(maximum_m / 100.0)) + 1)
    )
    prepare(water)
    output = np.empty((len(longitudes), 16), dtype=float)
    for offset in range(0, len(longitudes), cell_chunk):
        lon = np.repeat(
            np.asarray(longitudes[offset : offset + cell_chunk], dtype=float), 16
        )
        lat = np.repeat(
            np.asarray(latitudes[offset : offset + cell_chunk], dtype=float), 16
        )
        bearing = np.tile(bearings, len(lon) // 16)
        active = np.arange(len(lon))
        values = np.full(len(lon), float(maximum_m))
        start = 0
        for end in sorted(
            set([min(16, len(distances)), min(64, len(distances)), len(distances)])
        ):
            if not len(active):
                break
            ds = distances[start:end]
            count = len(ds)
            xs, ys, _ = GEOD.fwd(
                np.repeat(lon[active], count),
                np.repeat(lat[active], count),
                np.repeat(bearing[active], count),
                np.tile(ds, len(active)),
            )
            if start >= 64 and end == len(distances) and count >= 2:
                # A wholly covered connecting line certifies its sample points. A failed
                # certificate always falls back to the original point-sampling rule.
                coordinates = np.stack(
                    [xs.reshape(len(active), count), ys.reshape(len(active), count)],
                    axis=-1,
                )
                clear = np.asarray(covers(water, linestrings(coordinates)), dtype=bool)
                xs = xs.reshape(len(active), count)[~clear].ravel()
                ys = ys.reshape(len(active), count)[~clear].ravel()
                active = active[~clear]
                if not len(active):
                    break
            inside = np.asarray(covers(water, points(xs, ys)), dtype=bool).reshape(
                len(active), count
            )
            hit = (~inside).any(axis=1)
            first = np.argmax(~inside[hit], axis=1) + start
            values[active[hit]] = float(maximum_m) * np.clip(
                distances[np.maximum(first - 1, 0)] / float(maximum_m), 0.0, 1.0
            )
            active = active[~hit]
            start = end
        output[offset : offset + len(lon) // 16] = values.reshape(-1, 16)
    return output
