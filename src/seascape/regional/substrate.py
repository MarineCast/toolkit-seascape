"""Direct R6 coarse substrate point sampling; never an areal estimator."""

import math

import numpy as np

METHOD = "direct_native_R6_representative_point_bilinear_percent_v1"


def blend(values, weights, masks):
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    valid = ~np.asarray(masks, dtype=bool) & np.isfinite(values)
    if np.any(valid & ((values < 0) | (values > 100))):
        raise ValueError("Source percent outside [0,100]")
    retained = np.where(valid, weights, 0.0)
    total = retained.sum(axis=-1)
    numerator = (np.where(valid, values, 0.0) * retained).sum(axis=-1)
    result = np.divide(
        numerator, total, out=np.full_like(total, np.nan), where=total > 0
    )
    return (result / 100.0, total, (valid & (weights > 0)).sum(axis=-1))


def sediment_summary(gravel, sand, mud):
    v = np.asarray([gravel, sand, mud], dtype=float)
    if not np.isfinite(v).all():
        return ("source_texture_unavailable", None, None)
    total = float(v.sum())
    if total <= 0:
        return ("no_sediment_texture_mass", total, None)
    if not np.isclose(total, 1.0, atol=0.001):
        return ("source_texture_not_closed", total, None)
    positive = v[v > 0]
    return (
        "valid_closed",
        total,
        float(-(positive * np.log(positive)).sum() / math.log(3)),
    )


def sample(source, longitude, latitude):
    from rasterio.windows import Window

    if (
        source.crs.to_epsg() != 4326
        or source.scales != (1.0,)
        or source.offsets != (0.0,)
    ):
        raise ValueError("Unsupported CRS/scale/offset")
    if source.nodata != -99.0 or source.width != 3600 or source.height != 1800:
        raise ValueError("Unexpected source encoding")
    x, y = ~source.transform * (np.asarray(longitude), np.asarray(latitude))
    x, y = (x - 0.5, y - 0.5)
    c, r = (np.floor(x).astype(int), np.floor(y).astype(int))
    if np.any((c < 0) | (r < 0) | (c + 1 >= source.width) | (r + 1 >= source.height)):
        raise ValueError("Pilot point outside four-neighbour support")
    cmin, rmin = (int(c.min()), int(r.min()))
    window = Window(cmin, rmin, int(c.max()) + 2 - cmin, int(r.max()) + 2 - rmin)
    data = source.read(1, window=window, masked=True)
    cc = np.stack([c, c + 1, c, c + 1], axis=-1) - cmin
    rr = np.stack([r, r, r + 1, r + 1], axis=-1) - rmin
    values = data.data[rr, cc]
    masks = np.ma.getmaskarray(data)[rr, cc]
    dx, dy = (x - c, y - r)
    weights = np.stack(
        [(1 - dx) * (1 - dy), dx * (1 - dy), (1 - dx) * dy, dx * dy], axis=-1
    )
    result, support, count = blend(values, weights, masks)
    finite = data.compressed()
    if np.any(~np.isfinite(finite)) or np.any((finite < 0) | (finite > 100)):
        raise ValueError("Invalid regional window source values")
    qc = dict(
        window=list(window.flatten()),
        valid_pixels=int(finite.size),
        masked_pixels=int(np.ma.getmaskarray(data).sum()),
        minimum_percent=float(finite.min()) if finite.size else None,
        maximum_percent=float(finite.max()) if finite.size else None,
        scales=list(source.scales),
        offsets=list(source.offsets),
        nodata=source.nodata,
    )
    return (result, support, count, qc)


def scalar(source, longitude, latitude):
    """Independent georeferencing and per-neighbour scalar reads."""
    from rasterio.windows import Window

    col = (longitude - source.transform.c) / source.transform.a - 0.5
    row = (latitude - source.transform.f) / source.transform.e - 0.5
    c, r = (math.floor(col), math.floor(row))
    numerator = denominator = 0.0
    count = 0
    for dr in (0, 1):
        for dc in (0, 1):
            weight = (col - c if dc else 1 - col + c) * (row - r if dr else 1 - row + r)
            value = source.read(1, window=Window(c + dc, r + dr, 1, 1), masked=True)[
                0, 0
            ]
            if not np.ma.is_masked(value) and math.isfinite(float(value)):
                if not 0 <= float(value) <= 100:
                    raise ValueError("Scientific validation failed")
                numerator += float(value) * weight
                denominator += weight
                count += weight > 0
    return (
        numerator / denominator / 100 if denominator > 0 else float("nan"),
        denominator,
        count,
    )
