#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Visual comparison with magnified crops, for real logos.

Averaged metrics mislead: SSIM moved by three thousandths while the result looked
clearly worse, because its value is dominated by large flat areas and it does not
register a face disappearing.

Crops are chosen **automatically** as the windows with the highest error density
against the input, so the result does not depend on guessing which zones matter.
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import render_svg_bytes  # noqa: E402

RESULTS = ROOT / "results/real"


def _encode(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def worst_windows(
    error_map: np.ndarray, side: int, count: int
) -> list[tuple[int, int]]:
    """The ``count`` windows of ``side`` px holding the most error."""
    height, width = error_map.shape
    step = side // 2
    integral = error_map.cumsum(axis=0).cumsum(axis=1)

    def window_sum(y: int, x: int) -> float:
        y1, x1 = min(y + side, height) - 1, min(x + side, width) - 1
        total = integral[y1, x1]
        if y:
            total -= integral[y - 1, x1]
        if x:
            total -= integral[y1, x - 1]
        if y and x:
            total += integral[y - 1, x - 1]
        return float(total)

    candidates = [
        (window_sum(y, x), y, x)
        for y in range(0, max(height - side, 1), step)
        for x in range(0, max(width - side, 1), step)
    ]
    candidates.sort(reverse=True)

    chosen: list[tuple[int, int]] = []
    for _score, y, x in candidates:
        # Non-overlapping, so the page does not show the same spot five times.
        if all(abs(y - cy) >= side or abs(x - cx) >= side for cy, cx in chosen):
            chosen.append((y, x))
        if len(chosen) >= count:
            break
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", type=int, default=200, help="crop side in px")
    parser.add_argument("--zoom", type=int, default=3)
    parser.add_argument("--crops", type=int, default=3)
    parser.add_argument("--px", type=int, default=1024, help="render size")
    args = parser.parse_args()

    inputs = sorted((RESULTS / "input").glob("*.png"))
    if not inputs:
        print("run bench/run_real.py first", file=sys.stderr)
        return 1

    html = [
        "<meta charset='utf-8'><title>svgseg: fine detail crops</title>",
        "<style>body{font:13px system-ui;margin:20px;background:#fff;color:#111}"
        "table{border-collapse:collapse;margin-bottom:28px}"
        "td,th{border:1px solid #ddd;padding:3px;text-align:center;vertical-align:top}"
        "img{display:block;image-rendering:pixelated}"
        "h2{margin:22px 0 6px}.meta{font:11px monospace;color:#666}</style>",
        "<p>Crops chosen automatically by error density. <b>Magnified with "
        "nearest neighbour</b>, so the pixelation comes from the zoom, "
        "not the SVG.</p>",
    ]

    for input_path in inputs:
        svg_path = RESULTS / "svg" / f"{input_path.stem}.svg"
        if not svg_path.exists():
            continue
        reference = Image.open(input_path).convert("RGB")
        reference = reference.resize((args.px, args.px), Image.LANCZOS)
        render = render_svg_bytes(svg_path.read_bytes(), args.px, "#ffffff")
        error_map = np.asarray(
            deltaE_ciede2000(
                rgb2lab(np.asarray(reference) / 255.0), rgb2lab(render / 255.0)
            )
        )
        windows = worst_windows(error_map, args.side, args.crops)

        html.append(
            f"<h2>{input_path.stem}</h2><table>"
            "<tr><th>zone</th><th>input</th><th>output</th></tr>"
        )
        zoomed = args.side * args.zoom
        for number, (y, x) in enumerate(windows, 1):
            box = (x, y, x + args.side, y + args.side)
            mean_error = float(error_map[y : y + args.side, x : x + args.side].mean())
            crop_input = reference.crop(box).resize((zoomed, zoomed), Image.NEAREST)
            crop_output = (
                Image.fromarray(render)
                .crop(box)
                .resize((zoomed, zoomed), Image.NEAREST)
            )
            html.append(
                f"<tr><td class='meta'>{number}<br>{x},{y}</td>"
                f"<td><img width='{zoomed}' src='data:image/png;base64,"
                f"{_encode(crop_input)}'></td>"
                f"<td><img width='{zoomed}' src='data:image/png;base64,"
                f"{_encode(crop_output)}'>"
                f"<div class='meta'>mean dE {mean_error:.1f}</div></td></tr>"
            )
        html.append("</table>")
        print(f"{input_path.stem}: {len(windows)} crops")

    out = ROOT / "results/crops.html"
    out.write_text("\n".join(html))
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
