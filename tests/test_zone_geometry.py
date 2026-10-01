import math
import pytest
from xrv22.library.zone_geometry import (
    compute_plane_axis, compute_centroid, is_colinear, ColinearPointsError,
)


def test_centroid_3_points():
    pts = [[0, 0, 0], [10, 0, 0], [0, 10, 0]]
    c = compute_centroid(pts)
    assert c == pytest.approx([10 / 3, 10 / 3, 0])


def test_centroid_4_points():
    pts = [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]
    assert compute_centroid(pts) == pytest.approx([5, 5, 0])


def test_plane_axis_XY_floor():
    # Plan horizontal, normale ~ (0,0,1)
    assert compute_plane_axis([[0, 0, 0], [10, 0, 0], [0, 10, 0]]) == "XY"


def test_plane_axis_XZ_front_wall():
    # Plan dans XZ, normale ~ (0,1,0)
    assert compute_plane_axis([[0, 0, 0], [10, 0, 0], [0, 0, 10]]) == "XZ"


def test_plane_axis_YZ_side_wall():
    # Plan dans YZ, normale ~ (1,0,0)
    assert compute_plane_axis([[0, 0, 0], [0, 10, 0], [0, 0, 10]]) == "YZ"


def test_plane_axis_oblique():
    # Normale (1,1,1)/sqrt(3) -> aucune composante > cos(20°) ≈ 0.94
    assert compute_plane_axis([[0, 0, 0], [1, 0, -1], [0, 1, -1]]) == "oblique"


def test_plane_axis_within_20deg_tolerance():
    # Plan presque horizontal : normale ~ (sin10°, 0, cos10°)
    s, c = math.sin(math.radians(10)), math.cos(math.radians(10))
    pts = [[0, 0, 0], [c, 0, -s], [0, 1, 0]]
    assert compute_plane_axis(pts) == "XY"


def test_is_colinear_true():
    assert is_colinear([[0, 0, 0], [1, 1, 1], [2, 2, 2]]) is True


def test_is_colinear_false():
    assert is_colinear([[0, 0, 0], [1, 0, 0], [0, 1, 0]]) is False


def test_plane_axis_colinear_raises():
    with pytest.raises(ColinearPointsError):
        compute_plane_axis([[0, 0, 0], [1, 1, 1], [2, 2, 2]])
