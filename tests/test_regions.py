# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Region tests: connected components and the speck filter."""

from __future__ import annotations

import numpy as np

from svgseg.regions import OUTSIDE, merge_specks, segment_raw


def test_same_color_disjoint_pieces_become_separate_regions():
    """The defect that motivated the project.

    Three squares sharing an exact colour but not touching must be three
    regions, not one region with three parts.
    """
    labels = np.zeros((20, 60), np.int32)
    for offset in (2, 22, 42):
        labels[5:15, offset : offset + 10] = 1

    regions = segment_raw(labels)
    # One region for the background plus one per square.
    assert len(regions.areas) == 4
    assert (regions.color_index == 1).sum() == 3


def test_paint_order_is_largest_first():
    labels = np.zeros((20, 20), np.int32)
    labels[0:4, 0:4] = 1  # Small.
    labels[8:18, 8:18] = 2  # Large.

    regions = segment_raw(labels)
    ordered_areas = regions.areas[regions.order]
    assert list(ordered_areas) == sorted(ordered_areas, reverse=True)


def test_alpha_excludes_transparent_pixels():
    labels = np.zeros((10, 10), np.int32)
    alpha = np.ones((10, 10))
    alpha[:, 5:] = 0.0

    regions = segment_raw(labels, alpha)
    assert (regions.region_map[:, 5:] == OUTSIDE).all()
    assert (regions.region_map[:, :5] >= 0).all()


def test_merge_specks_absorbs_a_tiny_region():
    labels = np.zeros((20, 20), np.int32)
    labels[10, 10] = 1  # A single pixel of another colour.

    raw = segment_raw(labels)
    assert len(raw.areas) == 2
    merged = merge_specks(raw, min_area=4)
    assert len(merged.areas) == 1


def test_merge_specks_keeps_a_thin_long_region_when_min_length_is_set():
    """A 1x18 stroke is minuscule in area yet a deliberate design element.

    Filtering by area alone erases it; the shape criterion keeps it.
    """
    labels = np.zeros((20, 20), np.int32)
    labels[10, 1:19] = 1  # 18 px long, 1 px thick.

    raw = segment_raw(labels)
    absorbed = merge_specks(raw, min_area=100, min_length=0)
    preserved = merge_specks(raw, min_area=100, min_length=10)
    assert len(absorbed.areas) == 1
    assert len(preserved.areas) == 2


def test_region_without_neighbour_is_dropped_not_kept():
    """The alpha-fringe bug: an island floating in the transparent area.

    It has no neighbour to merge into, and the loop used to skip it, so it
    survived as a path forever. It must be discarded instead.
    """
    labels = np.zeros((20, 20), np.int32)
    alpha = np.zeros((20, 20))
    alpha[2:6, 2:6] = 1.0  # A real piece.
    alpha[15, 15] = 1.0  # An isolated speck surrounded by transparency.

    raw = segment_raw(labels, alpha)
    assert len(raw.areas) == 2
    merged = merge_specks(raw, min_area=4)
    assert len(merged.areas) == 1
    assert merged.region_map[15, 15] == OUTSIDE
