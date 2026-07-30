#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Objective metrics comparing an SVG against a known ground truth.

The core idea: instead of rasterizing every ``<path>`` separately (expensive), the
output SVG is recoloured so each shape gets a unique id colour, then rendered
TWICE, once in normal paint order and once reversed.

  - normal order   -> the output label map (for mIoU and colour fidelity)
  - reversed order -> wherever the two disagree, two or more shapes overlap
  - wherever both hold the background sentinel, no path covers that pixel

That directly quantifies the "stacked layers" defect: a vectorizer emitting full
overlapping silhouettes yields a huge overlap area, while a clean partition
yields zero.

BEWARE of antialiasing when decoding. With consecutive id colours, an edge
between shape 0 and shape 8 produces intermediate values 1..7 which are perfectly
valid ids, and the map ends up contaminated without anyone noticing. That is why
ids are spaced four apart per channel here, rendering is supersampled, and only
pixels whose colour matches an id EXACTLY are accepted; the rest are discarded and
each final pixel is decided by majority among its subsamples.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import numpy as np
from lxml import etree
from PIL import Image
from scipy import ndimage
from scipy.optimize import linear_sum_assignment
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from bench.inkscape_cli import export_png

SVG_NS = "http://www.w3.org/2000/svg"
DRAWABLES = {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}
SKIP_ANCESTORS = {"defs", "clipPath", "mask", "pattern", "marker", "symbol"}

STEP = 4  # Spacing between consecutive channel values of an id colour.
BASE = 2  # Offset, so no channel ever lands on 0 or 255.

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
_TOKENS = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


# --- SVG helpers ----------------------------------------------------------


def _tag(element) -> str:
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _style_dict(element) -> dict[str, str]:
    raw = element.get("style") or ""
    out = {}
    for part in raw.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def _resolve_fill(element) -> str:
    node = element
    while node is not None:
        style = _style_dict(node)
        value = style.get("fill") or node.get("fill")
        if value and value != "inherit":
            return value
        node = node.getparent()
    return "#000000"


def _parse_color(value: str) -> tuple[int, int, int] | None:
    value = (value or "").strip().lower()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            return tuple(int(c * 2, 16) for c in digits)  # type: ignore[return-value]
        if len(digits) == 6:
            return tuple(  # type: ignore[return-value]
                int(digits[i : i + 2], 16) for i in (0, 2, 4)
            )
    match = re.match(r"rgb\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", value)
    if match:
        return tuple(  # type: ignore[return-value]
            int(round(float(group))) for group in match.groups()
        )
    return {"white": (255, 255, 255), "black": (0, 0, 0)}.get(value)


def id_to_rgb(index: int) -> str:
    red = ((index // 4096) % 64) * STEP + BASE
    green = ((index // 64) % 64) * STEP + BASE
    blue = (index % 64) * STEP + BASE
    return f"#{red:02x}{green:02x}{blue:02x}"


def _valid_packed(id_count: int) -> np.ndarray:
    ids = np.arange(id_count + 1)
    red, green, blue = (ids // 4096) % 64, (ids // 64) % 64, ids % 64
    return (
        ((red * STEP + BASE) << 16)
        | ((green * STEP + BASE) << 8)
        | (blue * STEP + BASE)
    )


def decode_ids(
    rgb: np.ndarray, id_count: int, factor: int = 1
) -> tuple[np.ndarray, float]:
    """Decode a render of id colours.

    Only EXACT matches against a valid id colour are accepted; edge pixels, which
    are blends, come out invalid. With supersampling, each final pixel is resolved
    by majority among its valid subsamples.

    Returns (id map, fraction of unresolved pixels).
    """
    packed = (
        (rgb[:, :, 0].astype(np.int32) << 16)
        | (rgb[:, :, 1].astype(np.int32) << 8)
        | rgb[:, :, 2].astype(np.int32)
    )
    valid = _valid_packed(id_count)
    order = np.argsort(valid)
    sorted_valid = valid[order]
    position = np.clip(np.searchsorted(sorted_valid, packed), 0, len(sorted_valid) - 1)
    ids = np.where(sorted_valid[position] == packed, order[position], -1).astype(
        np.int32
    )

    if factor > 1:
        height, width = ids.shape[0] // factor, ids.shape[1] // factor
        blocks = (
            ids[: height * factor, : width * factor]
            .reshape(height, factor, width, factor)
            .transpose(0, 2, 1, 3)
            .reshape(height * width, factor * factor)
        )
        bins = id_count + 2
        out = np.empty(height * width, np.int32)
        chunk = max(1, 4_000_000 // bins)
        for start in range(0, height * width, chunk):
            block = blocks[start : start + chunk] + 1  # -1 (invalid) becomes 0.
            rows = block.shape[0]
            counts = np.bincount(
                (np.arange(rows)[:, None] * bins + block).ravel(),
                minlength=rows * bins,
            ).reshape(rows, bins)
            counts[:, 0] = 0  # Invalid subsamples never win the majority.
            out[start : start + chunk] = counts.argmax(axis=1) - 1
        ids = out.reshape(height, width)

    return ids, float(np.count_nonzero(ids < 0) / ids.size)


def _ancestor_transforms(element, root) -> list[str]:
    chain = []
    node = element.getparent()
    while node is not None and node is not root:
        if node.get("transform"):
            chain.append(node.get("transform"))
        node = node.getparent()
    return list(reversed(chain))


def collect_shapes(svg_path: Path):
    """Root plus drawable shapes in paint order: (element, transforms, fill)."""
    root = etree.parse(str(svg_path)).getroot()
    shapes = []
    for element in root.iter():
        if _tag(element) not in DRAWABLES:
            continue
        ancestor, skip = element.getparent(), False
        while ancestor is not None:
            if _tag(ancestor) in SKIP_ANCESTORS:
                skip = True
                break
            ancestor = ancestor.getparent()
        if skip:
            continue
        style = _style_dict(element)
        if (
            style.get("display") == "none"
            or style.get("fill") == "none"
            or element.get("fill") == "none"
        ):
            continue
        shapes.append(
            (element, _ancestor_transforms(element, root), _resolve_fill(element))
        )
    return root, shapes


def build_id_svg(root, shapes, px: int, reverse: bool) -> bytes:
    """Flattened SVG where shape i carries id colour i+1.

    Flattening is identical in both directions, so any imprecision affects both
    renders equally and overlap detection stays valid.
    """
    view_box = root.get("viewBox") or f"0 0 {px} {px}"
    out = etree.Element(
        f"{{{SVG_NS}}}svg",
        attrib={"width": str(px), "height": str(px), "viewBox": view_box},
    )
    order = list(enumerate(shapes, start=1))
    if reverse:
        order = order[::-1]
    for index, (element, transforms, _fill) in order:
        host = etree.SubElement(out, f"{{{SVG_NS}}}g")
        for transform in transforms:
            host = etree.SubElement(
                host, f"{{{SVG_NS}}}g", attrib={"transform": transform}
            )
        clone = etree.fromstring(etree.tostring(element))
        for attribute in (
            "style",
            "stroke",
            "stroke-width",
            "opacity",
            "fill-opacity",
            "filter",
            "mask",
        ):
            clone.attrib.pop(attribute, None)
        clone.set("fill", id_to_rgb(index))
        clone.set("stroke", "none")
        host.append(clone)
    return etree.tostring(out, xml_declaration=True, encoding="utf-8")


def render_svg_bytes(data: bytes, px: int, background: str = "#ffffff") -> np.ndarray:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "in.svg"
        target = Path(directory) / "out.png"
        source.write_bytes(data)
        export_png(source, target, px, background)
        return np.array(Image.open(target).convert("RGB"))


# --- metrics --------------------------------------------------------------


def split_connected(ids: np.ndarray) -> np.ndarray:
    """Split every ground-truth region into its connected components.

    A ground-truth region can be topologically disjoint: the hole of an "O" is
    background, yet separated from the outer background. Without this, an engine
    would be penalised for doing the right thing, which is emitting them as two
    pieces.

    Applied to the ground truth ONLY, never to the output: an engine putting
    disjoint pieces inside a single ``<path>`` is precisely the defect being
    measured.
    """
    structure = ndimage.generate_binary_structure(2, 2)
    out = np.zeros_like(ids)
    next_id = 1
    for value in np.unique(ids):
        components, count = ndimage.label(ids == value, structure=structure)
        mask = components > 0
        out[mask] = components[mask] + next_id - 1
        next_id += count
    return out


def _iou_matching(
    ground_truth: np.ndarray, output: np.ndarray
) -> tuple[float, dict[int, int]]:
    """Match ground-truth regions to output regions maximising total IoU."""
    gt_ids, out_ids = np.unique(ground_truth), np.unique(output)
    gt_position = {value: i for i, value in enumerate(gt_ids)}
    out_position = {value: i for i, value in enumerate(out_ids)}

    intersection = np.zeros((len(gt_ids), len(out_ids)), dtype=np.int64)
    pairs, counts = np.unique(
        np.stack([ground_truth.ravel(), output.ravel()], axis=1),
        axis=0,
        return_counts=True,
    )
    for (gt_value, out_value), count in zip(pairs, counts, strict=True):
        intersection[gt_position[gt_value], out_position[out_value]] = count

    union = (
        intersection.sum(axis=1, keepdims=True)
        + intersection.sum(axis=0, keepdims=True)
        - intersection
    )
    iou = np.where(union > 0, intersection / np.maximum(union, 1), 0.0)

    rows, columns = linear_sum_assignment(-iou)
    matched = {
        int(gt_ids[r]): int(out_ids[c]) for r, c in zip(rows, columns, strict=True)
    }
    scores = {
        int(gt_ids[r]): float(iou[r, c]) for r, c in zip(rows, columns, strict=True)
    }
    mean_iou = float(np.mean([scores.get(int(g), 0.0) for g in gt_ids]))
    return mean_iou, matched


def count_nodes(element) -> tuple[int, int]:
    """Count real segments rather than command letters.

    SVG allows implicit repetition: ``l0 -50 70 0 70 0`` is ONE ``l`` command with
    three segments. potrace uses it heavily, so counting letters underestimated
    the real count by roughly 500x. Each command's parameters must be consumed.
    """
    if _tag(element) != "path":
        return 4, 1
    tokens = _TOKENS.findall(element.get("d") or "")
    nodes = subpaths = 0
    command = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command in "Zz":
                command = None
                continue
        if command is None:
            i += 1
            continue
        count = _PARAM_COUNT[command.lower()]
        if i + count > len(tokens):
            break
        i += count
        nodes += 1
        if command in "Mm":
            subpaths += 1
            # After a moveto, loose parameter pairs are implicit linetos.
            command = "l" if command == "m" else "L"
    return nodes, max(subpaths, 1)


def detail_band(
    rgb: np.ndarray, min_area_rel: float = 5e-4, radius: int = 2
) -> np.ndarray:
    """Pixels where an image's fine detail lives.

    They are the pixels of small colour components (an eye, a headlight, a 3 px
    line) plus those within ``radius`` of a colour edge. This is the zone SSIM
    practically ignores, because its value is dominated by large flat areas: an
    engine can erase a person's face and move SSIM by three thousandths. Measuring
    the error HERE ONLY is what detects that failure.

    Edges are located with the engine's own quantizer, which returns about five
    clean colours on these logos. Quantizing generically does not work: on an
    AI-upscaled image it finds edges everywhere and the band ends up covering 61%
    of the pixels, which is no longer fine detail. The band only decides WHERE the
    error is measured, never what the answer is.
    """
    from svgseg.quantize import quantize

    flat = quantize(rgb.astype(np.float64) / 255.0).labels
    structure = ndimage.generate_binary_structure(2, 2)

    labels, count = ndimage.label(flat + 1, structure=structure)
    small = np.zeros(rgb.shape[:2], bool)
    if count:
        areas = np.bincount(labels.ravel())
        threshold = max(4.0, min_area_rel * rgb[..., 0].size)
        tiny = np.flatnonzero(areas < threshold)
        if len(tiny):
            small = np.isin(labels, tiny)

    edge = ndimage.maximum_filter(flat, size=3) != ndimage.minimum_filter(flat, size=3)
    if radius > 1:
        edge = ndimage.binary_dilation(edge, structure, iterations=radius - 1)
    return small | edge


def detail_error(
    reference: np.ndarray, render: np.ndarray, band: np.ndarray, tol: float = 10.0
) -> tuple[float, float]:
    """(fraction of the detail band with visible error, global 99th percentile).

    Per-pixel deltaE CIEDE2000 is used; ``tol``=10 is a clearly perceptible colour
    error, not an antialiasing nuance.
    """
    delta = deltaE_ciede2000(rgb2lab(reference / 255.0), rgb2lab(render / 255.0))
    lost = float(
        np.count_nonzero(delta[band] > tol) / max(np.count_nonzero(band), 1) * 100
    )
    return lost, float(np.percentile(delta, 99))


def composite_on_white(png: Path) -> np.ndarray:
    """Composite the image over white, honouring its alpha.

    A plain ``convert("RGB")`` drops the alpha channel and keeps the raw RGB,
    which in the transparent area can be anything; that would skew SSIM and
    deltaE.
    """
    image = Image.open(png).convert("RGBA")
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    return np.array(Image.alpha_composite(background, image).convert("RGB"))


def evaluate(
    svg_path: Path,
    ground_truth_npy: Path,
    input_png: Path,
    px: int,
    elapsed: float,
) -> dict:
    """Measure one output SVG against the ground-truth id map of its case."""
    root, shapes = collect_shapes(svg_path)
    path_count = len(shapes)
    if path_count == 0:
        return {"error": "no shapes", "paths": 0, "seconds": elapsed}

    raw_truth = np.load(ground_truth_npy)
    # -1 marks the transparent area of the ground truth: it is not evaluated.
    valid = raw_truth >= 0
    truth = split_connected(raw_truth)
    valid_count = int(np.count_nonzero(valid))

    # Supersampling: 4x on small images, 2x on large ones to bound memory.
    factor = 4 if px <= 512 else 2
    forward, unresolved_forward = decode_ids(
        render_svg_bytes(build_id_svg(root, shapes, px, False), px * factor, "#000000"),
        path_count,
        factor,
    )
    reverse, unresolved_reverse = decode_ids(
        render_svg_bytes(build_id_svg(root, shapes, px, True), px * factor, "#000000"),
        path_count,
        factor,
    )

    covered = forward > 0
    overlap_map = (forward != reverse) & covered & (reverse > 0)
    overlap = float(np.count_nonzero(overlap_map & valid) / valid_count)
    # Overlap area alone cannot tell a harmless 1 px seam from full stacked
    # silhouettes. Eroding by 1 px leaves only the latter.
    thick_overlap = float(
        np.count_nonzero(ndimage.binary_erosion(overlap_map, iterations=factor) & valid)
        / valid_count
    )
    uncovered = float(np.count_nonzero((forward == 0) & valid) / valid_count)

    mean_iou, matched = _iou_matching(truth[valid], forward[valid])

    reference = composite_on_white(input_png)
    fills = {i: _parse_color(f) for i, (_, _, f) in enumerate(shapes, start=1)}
    deltas, weights = [], []
    for region in np.unique(truth[valid]):
        mask = (truth == region) & valid
        predicted = fills.get(matched.get(int(region), -1))
        if predicted is None:
            continue
        actual = reference[mask].mean(axis=0) / 255.0
        deltas.append(
            float(
                deltaE_ciede2000(
                    rgb2lab(actual.reshape(1, 1, 3)),
                    rgb2lab((np.array(predicted) / 255.0).reshape(1, 1, 3)),
                )[0, 0]
            )
        )
        weights.append(int(mask.sum()))
    delta_e = float(np.average(deltas, weights=weights)) if deltas else float("nan")

    nodes = [count_nodes(element) for element, _, _ in shapes]
    render = render_svg_bytes(svg_path.read_bytes(), px, "#ffffff")
    ssim = float(structural_similarity(reference, render, channel_axis=2))

    return {
        "paths": path_count,
        "gt_pieces": int(len(np.unique(truth[valid]))),
        "overlap_pct": overlap * 100,
        "thick_overlap_pct": thick_overlap * 100,
        "uncovered_pct": uncovered * 100,
        "mean_iou": mean_iou,
        "delta_e": delta_e,
        "ssim": ssim,
        "total_nodes": int(sum(n for n, _ in nodes)),
        "nodes_per_path": float(np.mean([n for n, _ in nodes])),
        "max_subpaths": int(max(s for _, s in nodes)),
        # Average of both renders, as a percentage.
        "unresolved_pct": (unresolved_forward + unresolved_reverse) * 50,
        "seconds": elapsed,
    }
