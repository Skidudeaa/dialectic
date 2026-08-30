"""Pure contracts for geo_scopes.point_in_geometry — the ray-cast test
llm/world_watch.py uses to tell a real contact inside a scope from one that
only falls inside the live adapters' padded bounding box.
"""

from geo_scopes import point_in_geometry

# A small polygon around the Strait of Hormuz, matching the shape the plan's
# own seed script draws — hand-authored, not to scale.
HORMUZ_RING = [[55.6, 26.0], [56.2, 25.6], [57.2, 25.9], [57.0, 26.9], [55.6, 26.0]]
HORMUZ_POLY = {"type": "Polygon", "coordinates": [HORMUZ_RING]}

# A square with a smaller square hole cut out of its middle.
OUTER_SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
INNER_HOLE = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
SQUARE_WITH_HOLE = {"type": "Polygon", "coordinates": [OUTER_SQUARE, INNER_HOLE]}

MULTI = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],
    ],
}


def test_point_inside_polygon_is_true():
    assert point_in_geometry(HORMUZ_POLY, 56.4, 26.2) is True


def test_point_inside_padded_bbox_but_outside_polygon_is_false():
    """The exact false-positive class this function exists to kill: a point
    that would pass the adapters' bbox+1.5deg fence (world_adapters.RoomFence)
    but sits outside the polygon a human actually drew."""
    assert point_in_geometry(HORMUZ_POLY, 57.5, 27.5) is False


def test_point_far_outside_is_false():
    assert point_in_geometry(HORMUZ_POLY, 0.0, 0.0) is False


def test_hole_is_excluded():
    assert point_in_geometry(SQUARE_WITH_HOLE, 5.0, 5.0) is False   # inside the hole
    assert point_in_geometry(SQUARE_WITH_HOLE, 1.0, 1.0) is True    # inside the ring, outside the hole
    assert point_in_geometry(SQUARE_WITH_HOLE, 20.0, 20.0) is False  # outside everything


def test_multipolygon_checks_every_polygon():
    assert point_in_geometry(MULTI, 1.0, 1.0) is True
    assert point_in_geometry(MULTI, 11.0, 11.0) is True
    assert point_in_geometry(MULTI, 5.0, 5.0) is False


def test_point_and_linestring_geometry_have_no_interior():
    assert point_in_geometry({"type": "Point", "coordinates": [56.3, 26.5]}, 56.3, 26.5) is False
    line = {"type": "LineString", "coordinates": [[55.3, 26.4], [56.0, 26.6], [57.4, 25.7]]}
    assert point_in_geometry(line, 56.0, 26.6) is False


def test_non_geometry_input_is_false():
    assert point_in_geometry({}, 0.0, 0.0) is False
    assert point_in_geometry(None, 0.0, 0.0) is False  # type: ignore[arg-type]
    assert point_in_geometry({"type": "Polygon", "coordinates": []}, 0.0, 0.0) is False
