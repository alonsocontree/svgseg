#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Measure real logos, where there is no ground truth.

Without the true pieces mIoU cannot be computed, but almost everything else can,
and it is exactly what decides whether the SVG is usable for editing:

    paths / nodes    editability
    overlap %        clean partition or stacked layers
    uncovered %      holes in the output
    detail %         error in the fine-detail band, which SSIM does not see
    colors           how many distinct tones survived

Every image is scaled to a common working size before measuring, so a 34 Mpx input
is not penalised for its cost alone.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import (  # noqa: E402
    build_id_svg,
    collect_shapes,
    count_nodes,
    decode_ids,
    detail_band,
    detail_error,
    render_svg_bytes,
)
from svgseg import vectorize  # noqa: E402

INPUTS = ROOT / "test_png"
RESULTS = ROOT / "results/real"


def prepare(source: Path, target_dir: Path, working_px: int) -> Path:
    """Scale the image to the working size, square, for simpler comparisons."""
    image = (
        Image.open(source)
        .convert("RGBA")
        .resize((working_px, working_px), Image.LANCZOS)
    )
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    target = target_dir / f"{source.stem}.png"
    Image.alpha_composite(background, image).convert("RGB").save(target)
    return target


def measure(svg_path: Path, input_png: Path, eval_px: int) -> dict:
    root, shapes = collect_shapes(svg_path)
    if not shapes:
        return {"error": "no shapes", "paths": 0}

    factor = 2
    forward, unresolved = decode_ids(
        render_svg_bytes(
            build_id_svg(root, shapes, eval_px, False), eval_px * factor, "#000000"
        ),
        len(shapes),
        factor,
    )
    reverse, _ = decode_ids(
        render_svg_bytes(
            build_id_svg(root, shapes, eval_px, True), eval_px * factor, "#000000"
        ),
        len(shapes),
        factor,
    )

    nodes = [count_nodes(element) for element, _, _ in shapes]
    reference = np.array(
        Image.open(input_png).convert("RGB").resize((eval_px, eval_px), Image.LANCZOS)
    )
    render = render_svg_bytes(svg_path.read_bytes(), eval_px, "#ffffff")
    colors = {fill.lower() for _, _, fill in shapes}
    # Fine detail is measured at native resolution: that is where it lives.
    native = np.array(Image.open(input_png).convert("RGB"))
    detail, percentile_99 = detail_error(
        native,
        render_svg_bytes(svg_path.read_bytes(), native.shape[1], "#ffffff"),
        detail_band(native),
    )

    return {
        "paths": len(shapes),
        "total_nodes": int(sum(n for n, _ in nodes)),
        "colors": len(colors),
        "overlap_pct": float(
            np.count_nonzero((forward != reverse) & (forward > 0) & (reverse > 0))
            / forward.size
            * 100
        ),
        "uncovered_pct": float(np.count_nonzero(forward == 0) / forward.size * 100),
        "ssim": float(structural_similarity(reference, render, channel_axis=2)),
        "detail_pct": detail,
        "p99_delta_e": percentile_99,
        "kilobytes": svg_path.stat().st_size // 1024,
        "unresolved_pct": unresolved * 100,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--working-px", type=int, default=1024, help="common input size"
    )
    parser.add_argument("--eval-px", type=int, default=768, help="evaluation size")
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    prepared_dir = RESULTS / "input"
    prepared_dir.mkdir(exist_ok=True)

    images = sorted(
        path
        for path in INPUTS.iterdir()
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    if not images:
        print(f"no images in {INPUTS}", file=sys.stderr)
        return 1

    rows = []
    for source in images:
        prepared = prepare(source, prepared_dir, args.working_px)
        out_dir = RESULTS / "svg"
        out_dir.mkdir(exist_ok=True)
        svg_path = out_dir / f"{source.stem}.svg"
        row: dict = {"logo": source.stem}
        try:
            started = time.perf_counter()
            vectorize(prepared, svg_path)
            row["seconds"] = time.perf_counter() - started
            row.update(measure(svg_path, prepared, args.eval_px))
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
            traceback.print_exc(limit=2)
        rows.append(row)
        status = row.get(
            "error",
            f"paths={row.get('paths')} nodes={row.get('total_nodes')} "
            f"SSIM={row.get('ssim', 0):.4f}",
        )
        print(f"{source.stem:26} {status}")

    (RESULTS / "raw.json").write_text(json.dumps(rows, indent=2))

    columns = [
        ("paths", "paths", "d"),
        ("total_nodes", "nodes", "d"),
        ("colors", "col", "d"),
        ("detail_pct", "detail%", ".2f"),
        ("p99_delta_e", "p99dE", ".2f"),
        ("overlap_pct", "overlap%", ".2f"),
        ("ssim", "SSIM", ".4f"),
        ("kilobytes", "KB", "d"),
        ("seconds", "s", ".1f"),
    ]
    header = f"\n{'logo':26} " + " ".join(f"{label:>9}" for _, label, _ in columns)
    print(header)
    print("-" * len(header))
    valid = [row for row in rows if "error" not in row]
    for row in rows:
        if "error" in row:
            print(f"{row['logo']:26} {row['error'][:60]}")
            continue
        print(
            f"{row['logo']:26} "
            + " ".join(f"{row[key]:>9{spec}}" for key, _, spec in columns)
        )

    def mean_spec(spec: str) -> str:
        """A mean is always a float, so integer columns need a float spec."""
        return ".0f" if spec == "d" else spec

    if valid:
        print(
            f"\n{'MEAN':26} "
            + " ".join(
                f"{sum(row[key] for row in valid) / len(valid):>9{mean_spec(spec)}}"
                for key, _, spec in columns
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
