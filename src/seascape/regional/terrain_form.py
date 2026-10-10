"""Native R8 terrain descriptors, independent of the full geomorphic classifier."""

import numpy as np

METHOD_VERSION = "native_R8_terrain_form_proxy_v1"
CLASS_NAMES = (
    "ELEVATED_TERRAIN_PROXY",
    "DEPRESSED_TERRAIN_PROXY",
    "STEEP_NEUTRAL_TERRAIN_PROXY",
    "LOW_SLOPE_NEUTRAL_TERRAIN_PROXY",
    "INTERMEDIATE_NEUTRAL_TERRAIN_PROXY",
)


def classify(depth, slope, position_z, focal_marine, context4_complete, position_qc):
    """Positive Z is relatively elevated seafloor: mean-neighbour depth minus focal.

    All inputs must be eligible, even for the precedence-leading position classes.
    Returns nullable labels and explicit reasons; never geological confidence.
    """
    d, s, z = (np.asarray(x, dtype="float64") for x in (depth, slope, position_z))
    marine = np.asarray(focal_marine, dtype=object)
    context = np.asarray(context4_complete, dtype=object)
    qc = np.asarray(position_qc, dtype=object)
    if d.ndim != 1 or any(x.shape != d.shape for x in (s, z, marine, context, qc)):
        raise ValueError("One-dimensional equal-shaped inputs required")
    labels = np.full(d.shape, None, dtype=object)
    reasons = np.full(d.shape, "eligible_proxy", dtype=object)
    # First unavailable/invalid reason wins; every underlying input is preserved.
    for condition, reason in (
        (~np.isfinite(d), "depth_unavailable"),
        (np.isfinite(d) & (d < 0), "invalid_positive_down_depth"),
        (
            ~np.fromiter(
                (
                    value is True or isinstance(value, np.bool_) and bool(value)
                    for value in marine
                ),
                dtype=bool,
            ),
            "native_marine_depth_not_present",
        ),
        (~np.isfinite(s), "native_slope_unavailable"),
        (np.isfinite(s) & ((s < 0) | (s > 90)), "invalid_native_slope_degrees"),
        (~np.isfinite(z), "terrain_position_unavailable"),
        (
            np.fromiter((value is not None for value in qc), dtype=bool),
            "terrain_position_qc_ineligible",
        ),
        (
            ~np.fromiter(
                (
                    value is True or isinstance(value, np.bool_) and bool(value)
                    for value in context
                ),
                dtype=bool,
            ),
            "incomplete_four_hop_context",
        ),
    ):
        reasons[condition & (reasons == "eligible_proxy")] = reason
    eligible = reasons == "eligible_proxy"
    labels[eligible & (z >= 1)] = CLASS_NAMES[0]
    labels[eligible & (z <= -1)] = CLASS_NAMES[1]
    neutral = eligible & (z > -1) & (z < 1)
    labels[neutral & (s >= 15)] = CLASS_NAMES[2]
    labels[neutral & (s <= 5)] = CLASS_NAMES[3]
    labels[neutral & (s > 5) & (s < 15)] = CLASS_NAMES[4]
    return labels, reasons
