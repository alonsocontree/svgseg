# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Progress reporting tests. No Qt and no display needed."""

from __future__ import annotations

import numpy as np
import pytest

from svgseg import vectorize
from svgseg.progress import (
    STAGE_ORDER,
    STAGE_QUANTIZE,
    STAGE_WEIGHTS,
    ProgressReporter,
)


def test_stage_weights_sum_to_one():
    """Otherwise the overall fraction never reaches 1.0, or overshoots it."""
    assert sum(STAGE_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_stage_has_a_weight():
    assert set(STAGE_WEIGHTS) == set(STAGE_ORDER)


def test_reporter_maps_each_stage_into_its_own_slice():
    seen: list[tuple[str, float]] = []
    reporter = ProgressReporter(lambda stage, fraction: seen.append((stage, fraction)))
    for stage in STAGE_ORDER:
        reporter.stage(stage, 0.0)
        reporter.stage(stage, 1.0)

    fractions = [fraction for _stage, fraction in seen]
    assert fractions == sorted(fractions), "overall progress must never go backwards"
    assert fractions[0] == pytest.approx(0.0)
    assert fractions[-1] == pytest.approx(1.0)


def test_reporter_clamps_out_of_range_fractions():
    seen: list[float] = []
    reporter = ProgressReporter(lambda _stage, fraction: seen.append(fraction))
    reporter.stage(STAGE_QUANTIZE, -5.0)
    reporter.stage(STAGE_QUANTIZE, 5.0)
    assert all(0.0 <= fraction <= 1.0 for fraction in seen)


def test_reporter_without_callback_is_a_no_op():
    reporter = ProgressReporter(None)
    reporter.stage(STAGE_QUANTIZE, 0.5)  # Must not raise.
    reporter.done()


def _flat_png(path, size: int = 96) -> None:
    from PIL import Image

    image = np.zeros((size, size, 3), np.uint8)
    image[:, :] = (255, 255, 255)
    image[20:70, 20:70] = (30, 60, 120)
    image[35:55, 35:55] = (220, 60, 50)
    Image.fromarray(image).save(path)


def test_vectorize_reports_monotonic_progress_ending_at_one(tmp_path):
    source = tmp_path / "in.png"
    _flat_png(source)
    seen: list[tuple[str, float]] = []

    vectorize(source, tmp_path / "out.svg", progress=lambda s, f: seen.append((s, f)))

    assert seen, "the callback must be invoked"
    fractions = [fraction for _stage, fraction in seen]
    assert all(0.0 <= fraction <= 1.0 for fraction in fractions)
    assert fractions == sorted(fractions)
    assert fractions[-1] == pytest.approx(1.0)
    assert {stage for stage, _ in seen} <= set(STAGE_ORDER)


def test_progress_callback_does_not_change_the_output(tmp_path):
    """The whole point: instrumenting must not alter a single byte."""
    source = tmp_path / "in.png"
    _flat_png(source)
    plain = tmp_path / "plain.svg"
    instrumented = tmp_path / "instrumented.svg"

    vectorize(source, plain)
    vectorize(source, instrumented, progress=lambda _s, _f: None)

    assert plain.read_bytes() == instrumented.read_bytes()


def test_raising_from_the_callback_cancels_and_writes_nothing(tmp_path):
    """Cancellation needs no extra API: the exception propagates untouched."""
    source = tmp_path / "in.png"
    _flat_png(source)
    output = tmp_path / "out.svg"

    class Stop(Exception):  # noqa: N818 - a cancellation is not an error
        pass

    def cancel_midway(_stage: str, fraction: float) -> None:
        if fraction > 0.5:
            raise Stop

    with pytest.raises(Stop):
        vectorize(source, output, progress=cancel_midway)

    assert not output.exists(), "a cancelled run must leave no output behind"
