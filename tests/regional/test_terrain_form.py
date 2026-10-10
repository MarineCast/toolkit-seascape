import numpy as np
import pytest

from seascape.regional.terrain_form import CLASS_NAMES, classify


def run(d=100, s=10, z=0, marine=True, context=True, qc=None):
    labels, reasons = classify([d], [s], [z], [marine], [context], [qc])
    return labels[0], reasons[0]


@pytest.mark.parametrize(
    "s,z,expected",
    [
        (20, 1, CLASS_NAMES[0]),
        (0, -1, CLASS_NAMES[1]),
        (15, 0, CLASS_NAMES[2]),
        (5, 0, CLASS_NAMES[3]),
        (5.000001, 0, CLASS_NAMES[4]),
        (14.999999, 0, CLASS_NAMES[4]),
        (0, 0.999999, CLASS_NAMES[3]),
        (0, -1.000001, CLASS_NAMES[1]),
    ],
)
def test_threshold_ties_and_precedence(s, z, expected):
    assert run(s=s, z=z) == (expected, "eligible_proxy")


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"d": np.nan}, "depth_unavailable"),
        ({"d": -1}, "invalid_positive_down_depth"),
        ({"marine": False}, "native_marine_depth_not_present"),
        ({"marine": None}, "native_marine_depth_not_present"),
        ({"s": np.nan}, "native_slope_unavailable"),
        ({"s": -1}, "invalid_native_slope_degrees"),
        ({"s": 91}, "invalid_native_slope_degrees"),
        ({"z": np.inf}, "terrain_position_unavailable"),
        (
            {"qc": "zero_neighbor_variance_nonzero_position"},
            "terrain_position_qc_ineligible",
        ),
        ({"context": False}, "incomplete_four_hop_context"),
    ],
)
def test_missing_or_bad_input_never_gets_supported_label(kwargs, reason):
    assert run(**kwargs) == (None, reason)


def test_positive_down_sign_zero_variance_and_chunk_order():
    # Focal 90m vs mean-neighbour100m is a relative elevation, not depression.
    assert run(z=(100 - 90) / 5)[0] == CLASS_NAMES[0]
    assert run(z=(100 - 110) / 5)[0] == CLASS_NAMES[1]
    assert run(s=0, z=0, qc=None)[0] == CLASS_NAMES[3]
    assert run(z=np.nan, qc="zero_neighbor_variance_nonzero_position")[0] is None
    d = [100] * 5
    s = [0, 5, 10, 15, 20]
    z = [-2, -1, 0, 1, 2]
    full = classify(d, s, z, [True] * 5, [True] * 5, [None] * 5)
    reversed_result = classify(d, s[::-1], z[::-1], [True] * 5, [True] * 5, [None] * 5)
    assert full[0].tolist() == reversed_result[0][::-1].tolist()
    left = classify(d[:2], s[:2], z[:2], [True] * 2, [True] * 2, [None] * 2)
    right = classify(d[2:], s[2:], z[2:], [True] * 3, [True] * 3, [None] * 3)
    assert full[0].tolist() == left[0].tolist() + right[0].tolist()
    assert not any(name in CLASS_NAMES for name in ["SILL", "CHANNEL", "CANYON_AXIS"])
    with pytest.raises(ValueError):
        classify([1, 2], [1], [0], [True], [True], [None])
