# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Geometry tests: path parsing, emission and primitive fitting.

These need neither Inkscape nor potrace, so they run in seconds.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from svgseg.geometry import (
    _exact_ellipse,
    _fit_circle,
    _fit_ellipse,
    _sample_points,
    _signed_area,
    emit_path,
    parse_path,
    straighten,
)


@pytest.mark.parametrize(
    ("data", "expected_anchors", "closed"),
    [
        ("M0 0 L10 0 L10 10 Z", [(0, 0), (10, 0), (10, 10)], True),
        ("M0 0 l10 0 0 10 -10 0 z", [(0, 0), (10, 0), (10, 10), (0, 10)], True),
        ("M5 5 c1 0 2 0 3 0", [(5, 5), (8, 5)], False),
        ("M0 0 H10 V10 Z", [(0, 0), (10, 0), (10, 10)], True),
        # Implicit repetition: one command letter, several segments.
        ("M0 0 L1 0 2 0 3 0", [(0, 0), (1, 0), (2, 0), (3, 0)], False),
    ],
)
def test_parse_path_anchors(data, expected_anchors, closed):
    subpath = parse_path(data)[0]
    anchors = [tuple(round(v, 6) for v in point) for point in subpath.anchors()]
    assert anchors[: len(expected_anchors)] == [
        tuple(float(v) for v in point) for point in expected_anchors
    ]
    assert subpath.closed is closed


def test_parse_path_empty():
    assert parse_path("") == []
    assert parse_path("M0 0") == []  # A lone moveto has no segments.


@pytest.mark.parametrize(
    "data",
    [
        "M0 0 L10 0 L10 10 Z",
        "M100.5 200.25 c1 2 3 4 5 6 7 8 9 10 11 12 Z",
        "M0 0 L1000 0 L1000 1000 L0 1000 Z",
    ],
)
def test_emit_path_round_trip(data):
    original = parse_path(data)[0].anchors()
    reparsed = parse_path(emit_path(parse_path(data)))[0].anchors()
    error = max(
        abs(a[0] - b[0]) + abs(a[1] - b[1])
        for a, b in zip(original, reparsed, strict=True)
    )
    assert error < 0.02


def test_emit_path_does_not_drift():
    """Relative deltas are measured against the already rounded position.

    Otherwise the rounding accumulates along a long chain. The error must stay
    bounded by one unit of the last decimal, not grow with the point count.
    """
    points = [(i * 3.333, i * 7.777) for i in range(400)]
    data = "M{} {} L".format(*points[0]) + " ".join(f"{x} {y}" for x, y in points[1:])
    original = parse_path(data)[0].anchors()
    reparsed = parse_path(emit_path(parse_path(data)))[0].anchors()
    error = max(
        abs(a[0] - b[0]) + abs(a[1] - b[1])
        for a, b in zip(original, reparsed, strict=True)
    )
    assert error <= 0.011


@pytest.mark.parametrize(
    ("radius", "centre"),
    [(50.0, (100.0, 100.0)), (7.0, (0.0, 0.0)), (300.0, (-40.0, 25.0))],
)
def test_fit_circle_is_exact_on_exact_points(radius, centre):
    angles = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    points = np.column_stack(
        [centre[0] + radius * np.cos(angles), centre[1] + radius * np.sin(angles)]
    )
    (cx, cy), fitted_radius, error = _fit_circle(points)
    assert fitted_radius == pytest.approx(radius, abs=1e-6)
    assert (cx, cy) == pytest.approx(centre, abs=1e-6)
    assert error < 1e-6


@pytest.mark.parametrize(
    ("a", "b", "theta", "centre"),
    [
        (80.0, 40.0, 0.0, (100.0, 100.0)),
        (50.0, 50.0, 0.0, (0.0, 0.0)),  # A circle is a special case.
        (120.0, 30.0, math.pi / 6, (300.0, -50.0)),
        (60.0, 45.0, math.pi / 3, (10.0, 10.0)),
    ],
)
def test_fit_ellipse_is_exact_even_when_rotated(a, b, theta, centre):
    t = np.linspace(0, 2 * math.pi, 60, endpoint=False)
    u, v = a * np.cos(t), b * np.sin(t)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    points = np.column_stack(
        [centre[0] + u * cos_t - v * sin_t, centre[1] + u * sin_t + v * cos_t]
    )
    fitted = _fit_ellipse(points)
    assert fitted is not None
    fitted_centre, fitted_a, fitted_b, _theta, error = fitted
    assert max(fitted_a, fitted_b) == pytest.approx(max(a, b), abs=0.01)
    assert min(fitted_a, fitted_b) == pytest.approx(min(a, b), abs=0.01)
    assert fitted_centre == pytest.approx(centre, abs=0.01)
    assert error < 0.01


def test_fit_ellipse_rejects_non_ellipse():
    """A straight line is not an ellipse and must not be reported as one."""
    points = np.column_stack([np.linspace(0, 100, 40), np.zeros(40)])
    assert _fit_ellipse(points) is None


@pytest.mark.parametrize("winding", [1.0, -1.0])
def test_exact_ellipse_preserves_winding(winding):
    """potrace marks holes with reversed winding.

    Emitting a primitive the wrong way round would fill the hole, so the sign of
    the signed area has to survive the replacement.
    """
    subpath = _exact_ellipse((100.0, 100.0), 80.0, 40.0, math.pi / 5, winding)
    points = _sample_points(subpath, per_curve=10)
    assert math.copysign(1.0, _signed_area(points)) == math.copysign(1.0, winding)


def test_exact_circle_round_trips_through_the_fit():
    """Four cubics approximate a circle to about 0.03% of the radius."""
    subpath = _exact_ellipse((100.0, 100.0), 50.0, 50.0, 0.0, 1.0)
    points = _sample_points(subpath, per_curve=8)
    _centre, radius, error = _fit_circle(points)
    assert radius == pytest.approx(50.0, abs=0.02)
    assert error < 0.02


def test_straighten_collapses_a_curve_that_is_already_straight():
    # Control points sitting on the chord: the curve is a line in disguise.
    subpaths = parse_path("M0 0 C10 0 20 0 30 0")
    straighten(subpaths, tol=0.35)
    assert [segment[0] for segment in subpaths[0].segments] == ["L"]


def test_straighten_merges_collinear_lines():
    subpaths = parse_path("M0 0 L10 0 L20 0 L30 0")
    straighten(subpaths, tol=0.35)
    assert len(subpaths[0].segments) == 1
    assert subpaths[0].segments[0][1] == (30.0, 0.0)


def test_straighten_keeps_a_real_corner():
    subpaths = parse_path("M0 0 L10 0 L10 10")
    straighten(subpaths, tol=0.35)
    assert len(subpaths[0].segments) == 2
