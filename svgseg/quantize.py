# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Colour quantization in CIELAB with explicit antialiasing resolution.

This is the stage that decides the final quality. A logo PNG carries 1-2 px of
blended pixels along every outline; quantizing naively turns that blend into new
colours and creates a spurious sliver region along EVERY edge. (It shows in the
baseline: Inkscape's multi-scan on a six-colour logo invents tones such as
#70a5a3 and #9d63ee, which are pure edge.)

The method:

  1. Classify every pixel as pure (locally constant neighbourhood) or mixed.
  2. Build the palette from pure pixels ONLY, so antialiasing cannot invent
     entries. Each group's representative is an exact colour from the image
     rather than an average, which preserves the original hex value.
  3. Resolve every mixed pixel as a matting problem: find the pair of palette
     colours (C1, C2) present in its neighbourhood and the alpha that best
     explains its colour as alpha*C1 + (1-alpha)*C2, then assign the dominant one.

The alpha of that blend is also the true sub-pixel position of the edge. Using it
to reposition the outline was tried and did not pay off (see the corresponding
README section), which is why it is not kept.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from skimage.color import rgb2lab

# Distinct pure colours considered when building the palette.
MAX_CANDIDATES = 20000


@dataclass
class Quantization:
    labels: np.ndarray  # HxW int32: index into palette
    palette: np.ndarray  # Kx3 uint8 RGB
    pure: np.ndarray  # HxW bool: pixel not affected by antialiasing
    texture: float  # Fraction of pixels with local variation; 0 = clean render


def estimate_texture(local_range: np.ndarray) -> float:
    """How much local variation the image has, as a fraction of pixels.

    It separates the three regimes cleanly, measured over the test set:

        clean vector render      0.01 - 0.05
        JPEG q75                 0.18
        AI-upscaled logo         0.16 - 0.70

    A "flat colour" logo that went through an AI upscaler has no flat colour at
    all: it arrives with tens of thousands of tones and soft edges.
    """
    return float((local_range >= 1.0).mean())


def auto_parameters(texture: float, pixel_count: int) -> tuple[float, int, int]:
    """Derive (min_delta_e, min_area, min_length) from noise level and size.

    With values meant for a clean render, a real logo fragments into thousands of
    pieces: 3345 regions were measured where there are about 30. Raising
    min_delta_e not only reduces the piece count, it also IMPROVES fidelity,
    because the palette stops fitting noise (12 colours and SSIM 0.969 against 7
    colours and SSIM 0.977 on the same logo).

    ``min_length`` guards against the opposite mistake. Calibrating min_area to
    reduce the piece count destroys fine detail: at min_area=3184 the person in
    the `wash` logo collapses into a silhouette. With min_length set, a region is
    absorbed only if it is also compact, so a 3x200 px outline survives on length
    even though its area is minuscule.

    It defaults to 0: compared against the shape criterion on real logos, the
    area-only filter gives cleaner edges and 2x to 5x fewer pieces. It preserves
    less tiny detail, but for a logo a tidy outline is usually preferable to
    fidelity against a blurry input. Raising it with ``--min-length`` protects
    thin long strokes at the cost of more jagged outlines where the input is soft.

    The constants are anchored in sweeps over the `wash` logo; expressing the
    area in parts per million keeps min_area independent of resolution.
    """
    excess = max(0.0, texture - 0.05)
    min_delta_e = float(np.clip(8.0 + 24.0 * excess, 8.0, 20.0))
    ppm = float(np.clip(12.0 + 600.0 * excess, 12.0, 400.0))
    min_area = max(4, int(round(pixel_count * ppm / 1e6)))
    min_length = 0
    return min_delta_e, min_area, min_length


def _unpack(packed: np.ndarray) -> np.ndarray:
    return np.stack(
        [(packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF], axis=1
    ).astype(np.uint8)


def _local_range(lab: np.ndarray) -> np.ndarray:
    """Colour spread in the 3x3 neighbourhood, as an L2 norm over the channels.

    It is 0 in flat areas and jumps at edges: this is the discriminator between a
    pure pixel and a mixed one.
    """
    lab32 = lab.astype(np.float32)
    kernel = np.ones((3, 3), np.uint8)
    return np.linalg.norm(cv2.dilate(lab32, kernel) - cv2.erode(lab32, kernel), axis=2)


def _extend_edge(
    lab: np.ndarray, inside: np.ndarray, iterations: int = 2
) -> np.ndarray:
    """Propagate the border colour into the transparent area.

    Without this, ``_local_range`` sees an enormous colour jump at the alpha
    boundary (where the stored RGB is usually black or garbage) and classifies the
    whole silhouette outline as "mixed", which is exactly where being wrong is
    most costly. Only a thin band needs filling: the 3x3 window looks no further.
    """
    out = lab.astype(np.float32).copy()
    known = inside.copy()
    box = np.ones((3, 3), np.float32)
    for _ in range(iterations):
        fresh = (
            cv2.dilate(known.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            & ~known
        )
        if not fresh.any():
            break
        count = cv2.filter2D(known.astype(np.float32), -1, box)
        for channel in range(3):
            total = cv2.filter2D(out[..., channel] * known, -1, box)
            out[..., channel] = np.where(
                fresh, total / np.maximum(count, 1e-6), out[..., channel]
            )
        known |= fresh
    return out


def _nearest(
    lab_flat: np.ndarray, palette_lab: np.ndarray, chunk: int = 1 << 19
) -> np.ndarray:
    """Index of the closest palette colour, chunked to bound memory."""
    out = np.empty(len(lab_flat), dtype=np.int32)
    for i in range(0, len(lab_flat), chunk):
        block = lab_flat[i : i + chunk]
        distance = ((block[:, None, :] - palette_lab[None, :, :]) ** 2).sum(axis=2)
        out[i : i + chunk] = np.argmin(distance, axis=1)
    return out


def _palette_residual(candidate_lab: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    """How far each colour is from being explainable by the current palette.

    A colour counts as explained when it is a palette entry or a blend of two of
    them, which is exactly what antialiasing produces. A high residual means the
    palette is missing a colour.
    """
    residual = np.linalg.norm(
        candidate_lab[:, None, :] - palette_lab[None, :, :], axis=2
    ).min(axis=1)
    count = len(palette_lab)
    for i in range(count):
        for j in range(i + 1, count):
            delta = palette_lab[i] - palette_lab[j]
            denominator = float(delta @ delta)
            if denominator < 1e-12:
                continue
            alpha = np.clip(
                ((candidate_lab - palette_lab[j]) @ delta) / denominator, 0.0, 1.0
            )
            blended = palette_lab[j] + alpha[:, None] * delta
            np.minimum(
                residual,
                np.linalg.norm(candidate_lab - blended, axis=1),
                out=residual,
            )
    return residual


def _expand_palette(
    palette_rgb: np.ndarray,
    palette_lab: np.ndarray,
    candidate_rgb: np.ndarray,
    candidate_lab: np.ndarray,
    counts: np.ndarray,
    max_colors: int,
    tol: float,
    min_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Recover colours that NEVER appear pure anywhere in the image.

    Without this, a stroke thinner than a pixel disappears entirely: it has no
    flat pixel, its colour never reaches the palette and it ends up assigned to
    the background. This happened with the thin-strokes case at 128 px, where the
    palette collapsed to a single colour and the whole image turned white.

    The candidate FARTHEST from what is explainable is chosen, not the most
    frequent one: the most extreme instance of a colour is the least contaminated
    by blending, so it lands closer to the real colour than any average.
    """
    live = np.flatnonzero(counts >= min_count)
    if len(live) == 0:
        return palette_rgb, palette_lab
    live = live[np.argsort(-counts[live])[:2000]]

    while len(palette_lab) < max_colors and len(live):
        residual = _palette_residual(candidate_lab[live], palette_lab)
        live = live[residual > tol]
        if len(live) == 0:
            break
        best = live[np.argmax(residual[residual > tol])]
        palette_rgb = np.vstack([palette_rgb, candidate_rgb[best]])
        palette_lab = np.vstack([palette_lab, candidate_lab[best]])
    return palette_rgb, palette_lab


def _build_palette(
    rgb: np.ndarray,
    pure: np.ndarray,
    min_delta_e: float,
    max_colors: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Palette by "leader" clustering over the most frequent pure colours.

    It walks the exact colours from most to least frequent and accepts a new one
    only when it sits more than ``min_delta_e`` away from every colour already
    chosen. For a flat logo this recovers the original colours exactly.
    """
    source = rgb[pure] if pure.any() else rgb.reshape(-1, 3)
    quantized = (source * 255.0).round().astype(np.uint32)
    packed = (quantized[:, 0] << 16) | (quantized[:, 1] << 8) | quantized[:, 2]
    unique, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts)[:MAX_CANDIDATES]
    candidate_rgb = _unpack(unique[order])
    candidate_lab = rgb2lab(candidate_rgb.reshape(-1, 1, 3) / 255.0).reshape(-1, 3)

    chosen: list[int] = []
    threshold = min_delta_e**2
    for i in range(len(candidate_lab)):
        if chosen:
            distance = ((candidate_lab[chosen] - candidate_lab[i]) ** 2).sum(axis=1)
            if distance.min() < threshold:
                continue
        chosen.append(i)
        if len(chosen) >= max_colors:
            break

    return candidate_rgb[chosen], candidate_lab[chosen]


def _resolve_mixed(
    lab: np.ndarray,
    labels: np.ndarray,
    pure: np.ndarray,
    palette_lab: np.ndarray,
    radius: int,
    mixed: np.ndarray | None = None,
) -> np.ndarray:
    """Assign the mixed pixels by solving the two-colour matting problem."""
    height, width = labels.shape
    count = len(palette_lab)
    if mixed is None:
        mixed = ~pure
    if not mixed.any():
        return labels

    # Which colours appear among the PURE pixels of the neighbourhood. This
    # restricts the candidate pairs to combinations that really touch there.
    kernel = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    present = np.empty((count, height, width), dtype=bool)
    for i in range(count):
        seeds = ((labels == i) & pure).astype(np.uint8)
        present[i] = cv2.dilate(seeds, kernel) > 0

    indices = np.flatnonzero(mixed.ravel())
    samples = lab.reshape(-1, 3)[indices]
    local = present.reshape(count, -1)[:, indices]  # count x M

    best_residual = np.full(len(indices), np.inf, np.float64)
    best_alpha = np.zeros(len(indices), np.float64)
    best_first = np.full(len(indices), -1, np.int32)
    best_second = np.full(len(indices), -1, np.int32)

    for i in range(count):
        for j in range(i + 1, count):
            allowed = local[i] & local[j]
            if not allowed.any():
                continue
            selected = np.flatnonzero(allowed)
            delta = palette_lab[i] - palette_lab[j]
            denominator = float(delta @ delta)
            if denominator < 1e-12:
                continue
            alpha = np.clip(
                ((samples[selected] - palette_lab[j]) @ delta) / denominator, 0.0, 1.0
            )
            blended = palette_lab[j] + alpha[:, None] * delta
            residual = np.linalg.norm(samples[selected] - blended, axis=1)
            wins = residual < best_residual[selected]
            winners = selected[wins]
            best_residual[winners] = residual[wins]
            best_alpha[winners] = alpha[wins]
            best_first[winners] = i
            best_second[winners] = j

    # Pixels with a single pure colour around them (or none): nearest palette hit.
    lonely = best_first < 0
    if lonely.any():
        labels.ravel()[indices[lonely]] = _nearest(samples[lonely], palette_lab)

    paired = ~lonely
    if paired.any():
        first_wins = best_alpha[paired] > 0.5
        assigned = np.where(first_wins, best_first[paired], best_second[paired]).astype(
            np.int32
        )
        labels.ravel()[indices[paired]] = assigned

    return labels


def quantize(
    rgb: np.ndarray,
    max_colors: int = 32,
    min_delta_e: float | None = None,
    flat_tol: float = 4.0,
    radius: int = 2,
    residual_tol: float = 10.0,
    inside: np.ndarray | None = None,
) -> Quantization:
    """Quantize a float RGB image in [0, 1] to a flat palette, without slivers.

    ``min_delta_e=None`` derives it from the image noise; see auto_parameters.

    ``inside`` is the mask of opaque pixels. Everything that decides the palette
    is restricted to it: otherwise the RGB of the transparent area, which is
    usually black or garbage, enters the palette and colours appear that do not
    exist in the logo.
    """
    all_opaque = inside is None or bool(inside.all())
    lab = rgb2lab(rgb)
    # The local range is measured on the extended border so no fake colour jump
    # is invented at the alpha boundary.
    local_range = _local_range(lab if all_opaque else _extend_edge(lab, inside))
    texture = estimate_texture(local_range if all_opaque else local_range[inside])
    if min_delta_e is None:
        min_delta_e = auto_parameters(texture, rgb[..., 0].size)[0]

    pure = local_range < flat_tol
    if not all_opaque:
        pure &= inside
    if pure.mean() < 0.01:  # Very noisy image: no usable flat areas.
        pure = np.ones(rgb.shape[:2], bool) if all_opaque else inside.copy()

    palette_rgb, palette_lab = _build_palette(rgb, pure, min_delta_e, max_colors)

    # Second pass over the opaque pixels, not only the pure ones: it recovers
    # colours that exist solely as blends (detail finer than one pixel).
    source = rgb if all_opaque else rgb[inside]
    quantized = (source * 255.0).round().astype(np.uint32).reshape(-1, 3)
    packed = (quantized[:, 0] << 16) | (quantized[:, 1] << 8) | quantized[:, 2]
    unique, counts = np.unique(packed, return_counts=True)
    order = np.argsort(-counts)[:MAX_CANDIDATES]
    candidate_rgb = _unpack(unique[order])
    candidate_lab = rgb2lab(candidate_rgb.reshape(-1, 1, 3) / 255.0).reshape(-1, 3)
    palette_rgb, palette_lab = _expand_palette(
        palette_rgb,
        palette_lab,
        candidate_rgb,
        candidate_lab,
        counts[order],
        max_colors,
        residual_tol,
        max(4, len(packed) // 20000),
    )

    labels = np.empty(rgb.shape[:2], np.int32)
    labels[pure] = _nearest(lab[pure], palette_lab)
    labels[~pure] = 0  # Provisional: _resolve_mixed decides.
    mixed = ~pure if all_opaque else (~pure & inside)
    labels = _resolve_mixed(lab, labels, pure, palette_lab, radius, mixed)

    return Quantization(labels=labels, palette=palette_rgb, pure=pure, texture=texture)
