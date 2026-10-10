import numpy as np
import pytest

from seascape.regional.substrate import blend, sample, sediment_summary


def test_zero_is_not_missing():
    value, weight, count = blend(
        [[0, -99, -99, -99]], [[0.25] * 4], [[False, True, True, True]]
    )
    assert value[0] == 0 and weight[0] == 0.25 and count[0] == 1


def test_missing_remains_null():
    value, weight, count = blend([[-99] * 4], [[0.25] * 4], [[True] * 4])
    assert np.isnan(value[0]) and weight[0] == 0 and count[0] == 0


def test_partial_weights_renormalize():
    value, weight, count = blend(
        [[20, 60, -99, -99]], [[0.1, 0.3, 0.2, 0.4]], [[False, False, True, True]]
    )
    assert (
        value[0] == pytest.approx(0.5)
        and weight[0] == pytest.approx(0.4)
        and count[0] == 2
    )


@pytest.mark.parametrize("bad", [-0.01, 100.01])
def test_range_rejected(bad):
    with pytest.raises(ValueError):
        blend([[bad] * 4], [[0.25] * 4], [[False] * 4])


@pytest.mark.parametrize(
    "v,status",
    [
        ([0.2, 0.3, 0.5], "valid_closed"),
        ([0, 0, 0], "no_sediment_texture_mass"),
        ([0.2, 0.2, 0.2], "source_texture_not_closed"),
        ([0.2, np.nan, 0.8], "source_texture_unavailable"),
    ],
)
def test_sediment_only_closure(v, status):
    assert sediment_summary(*v)[0] == status


def test_rock_independent_and_entropy():
    assert sediment_summary(1, 0, 0) == ("valid_closed", 1.0, 0.0)
    assert sediment_summary(1 / 3, 1 / 3, 1 / 3)[2] == pytest.approx(1.0)
    # No rock argument exists; sediment is not the complement of rock.


def test_nonfinite_missing():
    v, _, _ = blend([[np.nan, np.inf, 50, 50]], [[0.25] * 4], [[False] * 4])
    assert v[0] == 0.5


@pytest.mark.parametrize("scales,offsets", [((0.01,), (0.0,)), ((1.0,), (1.0,))])
def test_scale_offset_rejected(scales, offsets):
    from types import SimpleNamespace

    src = SimpleNamespace(
        crs=SimpleNamespace(to_epsg=lambda: 4326), scales=scales, offsets=offsets
    )
    with pytest.raises(ValueError, match="scale/offset"):
        sample(src, [0.0], [0.0])


def test_zero_weight_valid_neighbor_is_not_support():
    v, w, c = blend([[100, -99, -99, -99]], [[0, 0, 0, 1]], [[False, True, True, True]])
    assert np.isnan(v[0]) and w[0] == 0 and c[0] == 0
