# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Quantization tests: palette recovery and texture estimation."""

from __future__ import annotations

import numpy as np

from svgseg.quantize import auto_parameters, estimate_texture, quantize

FLAT_COLORS = [
    (0.90, 0.22, 0.27),
    (0.16, 0.61, 0.56),
    (0.15, 0.27, 0.33),
    (1.00, 1.00, 1.00),
]


def _flat_image(size: int = 64) -> np.ndarray:
    """Four exact colour bands, with no antialiasing at all."""
    image = np.zeros((size, size, 3), np.float64)
    band = size // len(FLAT_COLORS)
    for index, color in enumerate(FLAT_COLORS):
        image[index * band : (index + 1) * band] = color
    return image


def test_palette_recovers_the_exact_colors_of_a_flat_image():
    result = quantize(_flat_image())
    recovered = {tuple(row) for row in result.palette}
    expected = {
        tuple(np.round(np.array(color) * 255).astype(np.uint8)) for color in FLAT_COLORS
    }
    assert recovered == expected


def test_labels_index_the_palette_consistently():
    image = _flat_image()
    result = quantize(image)
    # Every pixel maps to a palette entry holding its own colour. The palette is
    # stored as 8-bit RGB, so the tolerance is half a quantization step.
    reconstructed = result.palette[result.labels] / 255.0
    assert np.abs(reconstructed - image).max() <= 0.5 / 255.0


def test_texture_separates_clean_from_noisy():
    clean = estimate_texture(np.zeros((64, 64)))
    noisy = estimate_texture(np.full((64, 64), 5.0))
    assert clean == 0.0
    assert noisy == 1.0


def test_auto_parameters_grow_with_noise():
    clean_delta_e, clean_area, clean_length = auto_parameters(0.02, 1_000_000)
    noisy_delta_e, noisy_area, _ = auto_parameters(0.60, 1_000_000)
    assert clean_delta_e == 8.0  # The validated value for a clean render.
    assert noisy_delta_e > clean_delta_e
    assert noisy_area > clean_area
    # The shape criterion is off by default; see the README.
    assert clean_length == 0


def test_min_area_scales_with_pixel_count_not_resolution():
    """Expressed in parts per million, so behaviour is resolution independent."""
    _, small, _ = auto_parameters(0.40, 1_000_000)
    _, large, _ = auto_parameters(0.40, 4_000_000)
    assert large == 4 * small


def test_transparent_pixels_do_not_pollute_the_palette():
    """The RGB stored under alpha 0 is often black and must be ignored."""
    image = _flat_image()
    image[:16] = 0.0  # Garbage where the image will be transparent.
    inside = np.ones(image.shape[:2], bool)
    inside[:16] = False

    result = quantize(image, inside=inside)
    recovered = {tuple(row) for row in result.palette}
    assert (0, 0, 0) not in recovered
