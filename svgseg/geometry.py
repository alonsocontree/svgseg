# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Path geometry: parsing, transformation and regularization.

A traced outline follows the pixel staircase: a straight edge comes out with
micro-kinks and a circle comes out as dozens of wobbling curves. The result looks
*traced* rather than *designed*, and it wastes nodes on top of that.

Four passes run here, ordered from the safest to the most aggressive:

  1. straighten     near-straight curves become line segments, and consecutive
                    near-collinear lines merge into one
  2. snap_to_axes   a near-horizontal or near-vertical line is aligned exactly,
                    keeping shared coordinates consistent between neighbours
  3. circles        a subpath that lies on a circle is replaced by four exact
                    Bezier curves
  4. ellipses       otherwise a conic is fitted; if it turns out to be an
                    ellipse, four exact Bezier curves again

Everything works in image pixel coordinates rather than potrace's internal
units, so every tolerance is expressed in pixels.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

# Magic constant to approximate a quarter circle with a cubic Bezier.
K_CIRCLE = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)

_TOKENS = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_PARAM_COUNT = {
    "m": 2,
    "l": 2,
    "h": 1,
    "v": 1,
    "c": 6,
    "s": 4,
    "q": 4,
    "t": 2,
    "a": 7,
    "z": 0,
}

Point = tuple[float, float]


@dataclass
class Subpath:
    """One subpath: a start point plus a chain of segments.

    A segment is either ``("L", end)`` or ``("C", control1, control2, end)``.
    """

    start: Point
    segments: list[tuple] = field(default_factory=list)
    closed: bool = False

    def anchors(self) -> list[Point]:
        return [self.start] + [s[-1] for s in self.segments]


# --- parsing and emission -------------------------------------------------


def parse_path(d: str) -> list[Subpath]:
    """Parse an SVG ``d`` attribute, honouring implicit command repetition."""
    tokens = _TOKENS.findall(d or "")
    subpaths: list[Subpath] = []
    current: Subpath | None = None
    pos: Point = (0.0, 0.0)
    subpath_start: Point = (0.0, 0.0)
    command: str | None = None
    i = 0

    def num(k: int) -> float:
        return float(tokens[i + k])

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command in "Zz":
                if current is not None:
                    current.closed = True
                    pos = subpath_start
                command = None
                continue
        if command is None:
            i += 1
            continue
        count = _PARAM_COUNT[command.lower()]
        if i + count > len(tokens):
            break
        relative = command.islower()
        bx, by = pos if relative else (0.0, 0.0)

        if command in "Mm":
            pos = (num(0) + bx, num(1) + by)
            subpath_start = pos
            current = Subpath(start=pos)
            subpaths.append(current)
            # Extra coordinate pairs after a moveto are implicit linetos.
            command = "l" if command == "m" else "L"
        elif command in "LlHhVv":
            if command in "Hh":
                pos = (num(0) + bx, pos[1])
            elif command in "Vv":
                pos = (pos[0], num(0) + by)
            else:
                pos = (num(0) + bx, num(1) + by)
            if current is not None:
                current.segments.append(("L", pos))
        elif command in "CcSsQqTt":
            if command in "Cc":
                control1 = (num(0) + bx, num(1) + by)
                control2 = (num(2) + bx, num(3) + by)
                end = (num(4) + bx, num(5) + by)
            elif command in "Ss":
                control1 = pos  # Approximation: previous control is not mirrored.
                control2 = (num(0) + bx, num(1) + by)
                end = (num(2) + bx, num(3) + by)
            else:  # Quadratics are promoted to cubics through their control.
                q = (num(0) + bx, num(1) + by) if command in "Qq" else pos
                end = (
                    (num(2) + bx, num(3) + by)
                    if command in "Qq"
                    else (num(0) + bx, num(1) + by)
                )
                control1 = (
                    pos[0] + 2 / 3 * (q[0] - pos[0]),
                    pos[1] + 2 / 3 * (q[1] - pos[1]),
                )
                control2 = (
                    end[0] + 2 / 3 * (q[0] - end[0]),
                    end[1] + 2 / 3 * (q[1] - end[1]),
                )
            if current is not None:
                current.segments.append(("C", control1, control2, end))
            pos = end
        else:  # Arcs: potrace never emits them, so the command is flattened.
            pos = (num(5) + bx, num(6) + by)
            if current is not None:
                current.segments.append(("L", pos))
        i += count

    return [s for s in subpaths if s.segments]


def _fmt(value: float) -> str:
    """Compact number: two decimals are plenty in pixel space."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def emit_path(subpaths: list[Subpath], decimals: int = 2) -> str:
    """Emit a ``d`` attribute using RELATIVE coordinates and implicit repetition.

    In absolute form an outline at 5841 px spends seven characters per number
    (``1536.25``) where the delta to the neighbour spends three (``-50``).
    Measured on a real logo, going relative more than pays for the decimals: in
    absolute form the file grew from 1158 KB to 1427 KB despite having 20% fewer
    nodes.

    Rounding accumulates if every delta is measured against the ideal position,
    so the ALREADY ROUNDED position is carried and deltas are measured against
    it. The error stays bounded by one unit of the last decimal, with no drift.
    """
    quantum = 10.0**decimals

    def rounded(value: float) -> float:
        return round(value * quantum) / quantum

    parts: list[str] = []
    for subpath in subpaths:
        cursor = (rounded(subpath.start[0]), rounded(subpath.start[1]))
        parts.append(f"M{_fmt(cursor[0])} {_fmt(cursor[1])}")
        mode = ""
        for segment in subpath.segments:
            if segment[0] == "L":
                if mode != "l":
                    parts.append("l")
                    mode = "l"
                end = (rounded(segment[1][0]), rounded(segment[1][1]))
                parts.append(f"{_fmt(end[0] - cursor[0])} {_fmt(end[1] - cursor[1])}")
                cursor = end
            else:
                if mode != "c":
                    parts.append("c")
                    mode = "c"
                points = [(rounded(p[0]), rounded(p[1])) for p in segment[1:]]
                parts.append(
                    " ".join(
                        f"{_fmt(p[0] - cursor[0])} {_fmt(p[1] - cursor[1])}"
                        for p in points
                    )
                )
                cursor = points[-1]
        if subpath.closed:
            parts.append("Z")
            mode = ""
    return " ".join(parts)


def transform(
    subpaths: list[Subpath], sx: float, sy: float, tx: float, ty: float
) -> None:
    """Apply a diagonal affine (scale plus translation) in place."""

    def apply(p: Point) -> Point:
        return (sx * p[0] + tx, sy * p[1] + ty)

    for subpath in subpaths:
        subpath.start = apply(subpath.start)
        subpath.segments = [
            (seg[0], *(apply(p) for p in seg[1:])) for seg in subpath.segments
        ]


# --- geometric helpers ----------------------------------------------------


def _sample_points(subpath: Subpath, per_curve: int = 4) -> np.ndarray:
    """Points along the subpath, used to fit primitives."""
    points = [subpath.start]
    p0 = subpath.start
    for segment in subpath.segments:
        if segment[0] == "L":
            points.append(segment[1])
            p0 = segment[1]
        else:
            c1, c2, p1 = segment[1], segment[2], segment[3]
            for j in range(1, per_curve + 1):
                t = j / per_curve
                u = 1 - t
                points.append(
                    (
                        u**3 * p0[0]
                        + 3 * u * u * t * c1[0]
                        + 3 * u * t * t * c2[0]
                        + t**3 * p1[0],
                        u**3 * p0[1]
                        + 3 * u * u * t * c1[1]
                        + 3 * u * t * t * c2[1]
                        + t**3 * p1[1],
                    )
                )
            p0 = p1
    return np.asarray(points, dtype=np.float64)


def _signed_area(points: np.ndarray) -> float:
    """Shoelace area. Its sign gives the winding direction."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def _distance_to_line(points: np.ndarray, a: Point, b: Point) -> np.ndarray:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return np.hypot(points[:, 0] - ax, points[:, 1] - ay)
    return np.abs((points[:, 0] - ax) * dy - (points[:, 1] - ay) * dx) / length


# --- 1. straighten: near-straight curves and collinear lines --------------


def straighten(subpaths: list[Subpath], tol: float = 0.35) -> None:
    """Near-straight curves become lines, near-collinear lines merge into one.

    ``tol`` is the maximum allowed deviation, in pixels. At 0.35 px the change is
    invisible but many nodes disappear: potrace emits curves for stretches that
    are actually straight with one antialiasing step.
    """
    for subpath in subpaths:
        # Curves whose control points sit on the chord.
        rebuilt = []
        p0 = subpath.start
        for segment in subpath.segments:
            if segment[0] == "C":
                controls = np.asarray([segment[1], segment[2]], dtype=np.float64)
                if _distance_to_line(controls, p0, segment[3]).max() <= tol:
                    segment = ("L", segment[3])
            rebuilt.append(segment)
            p0 = segment[-1]
        subpath.segments = rebuilt

        # Consecutive collinear lines.
        changed = True
        while changed and len(subpath.segments) > 1:
            changed = False
            merged = []
            p0 = subpath.start
            k = 0
            while k < len(subpath.segments):
                segment = subpath.segments[k]
                if (
                    segment[0] == "L"
                    and k + 1 < len(subpath.segments)
                    and subpath.segments[k + 1][0] == "L"
                ):
                    middle = np.asarray([segment[1]], dtype=np.float64)
                    end = subpath.segments[k + 1][1]
                    if _distance_to_line(middle, p0, end).max() <= tol:
                        merged.append(("L", end))
                        p0 = end
                        k += 2
                        changed = True
                        continue
                merged.append(segment)
                p0 = segment[-1]
                k += 1
            subpath.segments = merged


# --- 2. axes: align near-horizontal and near-vertical lines ---------------


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a


def snap_to_axes(
    subpaths: list[Subpath], tol: float = 0.6, min_length: float = 3.0
) -> None:
    """Align to the axes those lines that are already nearly aligned.

    An endpoint cannot be moved on its own: the coordinate is shared with the
    neighbouring segments and the outline would break. Anchors that must share an
    X (or a Y) are grouped with union-find and each group is set to its mean, so
    the whole chain of a vertical wall ends up on a single X.
    """
    for subpath in subpaths:
        anchors = subpath.anchors()
        n = len(anchors)
        union_x, union_y = _UnionFind(n), _UnionFind(n)
        if subpath.closed and n > 1:
            # On a closed subpath the last anchor coincides with the first.
            union_x.union(0, n - 1)
            union_y.union(0, n - 1)

        for k, segment in enumerate(subpath.segments):
            if segment[0] != "L":
                continue
            a, b = anchors[k], anchors[k + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            if math.hypot(dx, dy) < min_length:
                continue
            if abs(dx) <= tol and abs(dy) > tol:
                union_x.union(k, k + 1)  # Vertical: same X.
            elif abs(dy) <= tol and abs(dx) > tol:
                union_y.union(k, k + 1)  # Horizontal: same Y.

        xs = np.array([p[0] for p in anchors])
        ys = np.array([p[1] for p in anchors])
        for union, values in ((union_x, xs), (union_y, ys)):
            groups: dict[int, list[int]] = {}
            for k in range(n):
                groups.setdefault(union.find(k), []).append(k)
            for members in groups.values():
                if len(members) > 1:
                    values[members] = values[members].mean()

        snapped = [(float(xs[k]), float(ys[k])) for k in range(n)]
        subpath.start = snapped[0]
        subpath.segments = [
            (seg[0], *seg[1:-1], snapped[k + 1])
            for k, seg in enumerate(subpath.segments)
        ]


# --- 3 and 4. circles and ellipses ---------------------------------------


def _fit_circle(points: np.ndarray) -> tuple[Point, float, float]:
    """Algebraic circle fit. Returns (centre, radius, max_error)."""
    x, y = points[:, 0], points[:, 1]
    design = np.column_stack([x, y, np.ones_like(x)])
    rhs = -(x**2 + y**2)
    try:
        solution, *_ = np.linalg.lstsq(design, rhs, rcond=None)
    except np.linalg.LinAlgError:
        return (0.0, 0.0), 0.0, float("inf")
    cx, cy = -solution[0] / 2, -solution[1] / 2
    under_root = cx * cx + cy * cy - solution[2]
    if under_root <= 0:
        return (0.0, 0.0), 0.0, float("inf")
    radius = math.sqrt(under_root)
    error = float(np.abs(np.hypot(x - cx, y - cy) - radius).max())
    return (float(cx), float(cy)), radius, error


def _fit_ellipse(points: np.ndarray):
    """Fit a conic and return it as an ellipse: (centre, a, b, theta, max_error).

    Returns None when the conic is not an ellipse. Points are centred and scaled
    before solving: with unnormalised x^2 terms the system is ill-conditioned and
    the solution degrades at large image coordinates.
    """
    mean = points.mean(axis=0)
    scale = float(np.abs(points - mean).max())
    if scale < 1e-9:
        return None
    normalized = (points - mean) / scale
    x, y = normalized[:, 0], normalized[:, 1]
    design = np.column_stack([x * x, x * y, y * y, x, y, np.ones_like(x)])
    try:
        _, _, vt = np.linalg.svd(design, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    a_c, b_c, c_c, d_c, e_c, f_c = vt[-1]

    discriminant = b_c * b_c - 4 * a_c * c_c
    if discriminant >= -1e-12:  # Parabola or hyperbola.
        return None
    cx = (2 * c_c * d_c - b_c * e_c) / discriminant
    cy = (2 * a_c * e_c - b_c * d_c) / discriminant
    # Constant term translated to the centre.
    constant = a_c * cx * cx + b_c * cx * cy + c_c * cy * cy + d_c * cx + e_c * cy + f_c
    if abs(constant) < 1e-15:
        return None
    # Eigenvalues of the quadratic part give the semi-axes and the rotation.
    quadratic = np.array([[a_c, b_c / 2], [b_c / 2, c_c]]) / (-constant)
    values, vectors = np.linalg.eigh(quadratic)
    if np.any(values <= 0):
        return None
    axes = 1.0 / np.sqrt(values)
    theta = math.atan2(vectors[1, 0], vectors[0, 0])
    a, b = float(axes[0]), float(axes[1])

    # Radial error in the ellipse frame, converted back to pixels.
    cos_t, sin_t = math.cos(-theta), math.sin(-theta)
    dx, dy = x - cx, y - cy
    u = dx * cos_t - dy * sin_t
    v = dx * sin_t + dy * cos_t
    radial = np.sqrt((u / a) ** 2 + (v / b) ** 2)
    error = float(np.abs(radial - 1.0).max() * min(a, b) * scale)
    centre = (float(cx * scale + mean[0]), float(cy * scale + mean[1]))
    return centre, a * scale, b * scale, theta, error


def _exact_ellipse(
    centre: Point, a: float, b: float, theta: float, winding: float
) -> Subpath:
    """Ellipse as four cubic Beziers, matching the original winding direction.

    The direction matters: potrace uses the nonzero fill rule and marks holes
    with reversed winding, so emitting the ellipse backwards would fill the hole.
    """
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def at(u: float, v: float) -> Point:
        return (
            centre[0] + u * cos_t - v * sin_t,
            centre[1] + u * sin_t + v * cos_t,
        )

    ka, kb = K_CIRCLE * a, K_CIRCLE * b
    quarters = [
        (at(a, 0), at(a, kb), at(ka, b), at(0, b)),
        (at(0, b), at(-ka, b), at(-a, kb), at(-a, 0)),
        (at(-a, 0), at(-a, -kb), at(-ka, -b), at(0, -b)),
        (at(0, -b), at(ka, -b), at(a, -kb), at(a, 0)),
    ]
    if winding < 0:
        quarters = [(p3, c2, c1, p0) for p0, c1, c2, p3 in reversed(quarters)]
    subpath = Subpath(start=quarters[0][0], closed=True)
    for _p0, c1, c2, p3 in quarters:
        subpath.segments.append(("C", c1, c2, p3))
    return subpath


def fit_primitives(
    subpaths: list[Subpath],
    tol: float = 0.8,
    min_radius: float = 4.0,
    min_nodes: int = 5,
    max_axis_ratio: float = 8.0,
) -> list[Subpath]:
    """Replace subpaths that are circles or ellipses with exact primitives.

    This is the most visible win in a logo: a traced circle comes out as dozens
    of wobbling curves and becomes four perfect Beziers instead.
    """
    result = []
    for subpath in subpaths:
        if not subpath.closed or len(subpath.segments) < min_nodes:
            result.append(subpath)
            continue
        points = _sample_points(subpath)
        winding = _signed_area(points)

        def covers_full_turn(centre: Point, points: np.ndarray = points) -> bool:
            """Require a full turn: an arc also fits a conic."""
            angles = np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0])
            histogram, _ = np.histogram(angles, bins=12, range=(-math.pi, math.pi))
            return not (histogram == 0).any()

        # Try a circle first: it is the most robust fit and the common case.
        centre, radius, error = _fit_circle(points)
        if radius >= min_radius and error <= tol and covers_full_turn(centre):
            result.append(_exact_ellipse(centre, radius, radius, 0.0, winding))
            continue

        # Otherwise an ellipse. They show up often in logos, especially
        # flattened by perspective or in oval shapes.
        fitted = _fit_ellipse(points)
        if fitted is not None:
            centre, a, b, theta, error = fitted
            ratio = max(a, b) / max(min(a, b), 1e-9)
            if (
                min(a, b) >= min_radius
                and error <= tol
                # Flatter than this is no longer a deliberate ellipse.
                and ratio <= max_axis_ratio
                and covers_full_turn(centre)
            ):
                result.append(_exact_ellipse(centre, a, b, theta, winding))
                continue

        result.append(subpath)
    return result


# --- orchestration --------------------------------------------------------


def regularize_path(
    d: str,
    sx: float,
    sy: float,
    tx: float,
    ty: float,
    line_tol: float = 0.35,
    axis_tol: float = 0.6,
    circle_tol: float = 0.8,
) -> str:
    """Move the path into pixel space and regularize it. Returns the new ``d``.

    The result is in pixel coordinates, so the ``<path>`` no longer needs a
    transform of its own.
    """
    subpaths = parse_path(d)
    if not subpaths:
        return ""
    transform(subpaths, sx, sy, tx, ty)
    if circle_tol > 0:
        subpaths = fit_primitives(subpaths, tol=circle_tol)
    if line_tol > 0:
        straighten(subpaths, tol=line_tol)
    if axis_tol > 0:
        snap_to_axes(subpaths, tol=axis_tol)
    return emit_path(subpaths)
