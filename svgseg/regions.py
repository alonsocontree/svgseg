# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""From the colour map to a partition into pieces: connected components.

This is where the defect that breaks Inkscape is fixed: five disjoint blue
squares are five connected components, hence five selectable ``<path>`` elements,
instead of a single path holding five subpaths.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

OUTSIDE = -1  # Transparent pixel: produces no path.


@dataclass
class Regions:
    region_map: np.ndarray  # HxW int32 in [0, N), or OUTSIDE
    color_index: np.ndarray  # N: index into the palette
    areas: np.ndarray  # N: area in pixels
    order: np.ndarray  # N: ids sorted by descending area, i.e. paint order


def _structure(connectivity: int) -> np.ndarray:
    return ndimage.generate_binary_structure(2, 2 if connectivity == 8 else 1)


def _connected_components(
    labels: np.ndarray, inside: np.ndarray, connectivity: int
) -> tuple[np.ndarray, np.ndarray]:
    """Label connected components per colour and concatenate them globally."""
    structure = _structure(connectivity)
    region_map = np.full(labels.shape, OUTSIDE, np.int32)
    color_index: list[int] = []
    next_id = 0
    for color in np.unique(labels[inside]):
        components, count = ndimage.label(
            (labels == color) & inside, structure=structure
        )
        if count == 0:
            continue
        mask = components > 0
        region_map[mask] = components[mask] - 1 + next_id
        color_index.extend([int(color)] * count)
        next_id += count
    return region_map, np.array(color_index, np.int32)


def _adjacent_pairs(region_map: np.ndarray, n: int):
    """(a, b, shared_border_length) for every pair of touching regions."""
    axes = [
        (region_map[:, :-1].ravel(), region_map[:, 1:].ravel()),
        (region_map[:-1, :].ravel(), region_map[1:, :].ravel()),
    ]
    a = np.concatenate([axis[0] for axis in axes])
    b = np.concatenate([axis[1] for axis in axes])
    valid = (a != b) & (a >= 0) & (b >= 0)
    a, b = a[valid], b[valid]
    both_a = np.concatenate([a, b])  # Both directions.
    both_b = np.concatenate([b, a])
    key = both_a.astype(np.int64) * n + both_b
    unique, counts = np.unique(key, return_counts=True)
    return (unique // n).astype(np.int32), (unique % n).astype(np.int32), counts


# NOTE: a colour-contrast criterion was tried and discarded. It cannot work:
# regions exist precisely where the quantizer assigned different colours, so two
# adjacent regions ALWAYS differ by construction and the filter never fires
# (measured: 2230 regions in the `wash` logo where there should be ~70, for any
# min_area). Comparing palette colours or original image colours makes no
# difference. Shape is the only useful axis.


def _longest_side(region_map: np.ndarray, n: int) -> np.ndarray:
    """Longest bounding-box side of each region.

    This separates thin-but-long from merely tiny: a 3x200 px outline has a
    longest side of 200 and is a design decision, while a 3x4 px speck has 4 and
    is compression noise. Area alone does not tell them apart.
    """
    sides = np.zeros(n, np.int32)
    for region, box in enumerate(ndimage.find_objects(region_map + 1)):
        if box is not None:
            sides[region] = max(box[0].stop - box[0].start, box[1].stop - box[1].start)
    return sides


def _merge_specks(
    region_map: np.ndarray,
    color_index: np.ndarray,
    min_area: int,
    min_length: int = 0,
    max_passes: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Absorb tiny regions into the neighbour they share the longest border with.

    Area alone is the wrong criterion for deciding what is noise. A 3 px white
    outline against navy is minuscule in area and essential in meaning: filtering
    by size alone erases it, and with it the face of a person (measured: at
    min_area=3184 the `wash` logo collapses into silhouettes).

    A region is absorbed only when it is small in area **and** compact, meaning
    its longest side does not reach ``min_length`` either. A 3x200 outline has a
    longest side of 200 and survives; a 3x4 speck does not.
    """
    n = len(color_index)
    for _ in range(max_passes):
        areas = np.bincount(region_map[region_map >= 0].ravel(), minlength=n)
        alive = areas > 0
        small = np.flatnonzero(alive & (areas < min_area))
        if min_length > 0 and len(small):
            sides = _longest_side(region_map, n)
            small = small[sides[small] < min_length]
        if len(small) == 0:
            break

        a, b, border = _adjacent_pairs(region_map, n)
        is_small = np.zeros(n, bool)
        is_small[small] = True

        targets: dict[int, int] = {}
        to_drop: list[int] = []
        for region in small[np.argsort(areas[small])]:
            selected = a == region
            if not selected.any():
                # No neighbour to merge into. This happens with the antialiasing
                # fringe of a transparent PNG: islands of a few pixels float in
                # the transparent area, and because the loop used to skip them
                # they survived as paths forever (measured: 89 of 171 regions in
                # one logo, 0.005% of the total area).
                to_drop.append(int(region))
                continue
            neighbours, weights = b[selected], border[selected]
            large = ~is_small[neighbours]
            if large.any():
                neighbours, weights = neighbours[large], weights[large]
            elif len(neighbours) == 1 or is_small[neighbours].all():
                # Every neighbour is small too: wait for the next pass.
                continue
            targets[int(region)] = int(neighbours[np.argmax(weights)])

        if not targets and not to_drop:
            break

        if to_drop:
            region_map[np.isin(region_map, to_drop)] = OUTSIDE

        remap = np.arange(n, dtype=np.int32)
        for region, target in targets.items():
            remap[region] = target
        for _ in range(8):  # Resolve chains r -> s -> t.
            collapsed = remap[remap]
            if np.array_equal(collapsed, remap):
                break
            remap = collapsed

        inside = region_map >= 0
        region_map[inside] = remap[region_map[inside]]
        color_index = color_index.copy()
        for region in targets:
            color_index[region] = color_index[remap[region]]

    return region_map, color_index


def _finalize(region_map: np.ndarray, color_index: np.ndarray) -> Regions:
    """Reindex contiguously, dropping the regions that were absorbed."""
    alive = np.unique(region_map[region_map >= 0])
    remap = np.full(len(color_index), OUTSIDE, np.int32)
    remap[alive] = np.arange(len(alive), dtype=np.int32)
    inside = region_map >= 0
    region_map[inside] = remap[region_map[inside]]
    color_index = color_index[alive]

    areas = np.bincount(region_map[inside].ravel(), minlength=len(alive))
    # Descending area: the order in which the pieces will be painted.
    order = np.argsort(-areas, kind="stable").astype(np.int32)
    return Regions(
        region_map=region_map, color_index=color_index, areas=areas, order=order
    )


def segment_raw(
    labels: np.ndarray, alpha: np.ndarray | None = None, connectivity: int = 8
) -> Regions:
    """Partition into connected components, WITHOUT filtering specks."""
    inside = np.ones(labels.shape, bool) if alpha is None else alpha >= 0.5
    region_map, color_index = _connected_components(labels, inside, connectivity)
    if len(color_index) == 0:
        raise ValueError("the image has no opaque pixels")
    return _finalize(region_map, color_index)


def merge_specks(
    regions: Regions,
    min_area: int = 4,
    min_length: int = 0,
) -> Regions:
    """Apply the speck filter to an already computed partition."""
    if min_area <= 1:
        return regions
    region_map, color_index = _merge_specks(
        regions.region_map.copy(), regions.color_index, min_area, min_length
    )
    return _finalize(region_map, color_index)
