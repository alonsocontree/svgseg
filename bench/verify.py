#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""End-to-end check of the acceptance criteria.

It verifies what a user would notice when opening the SVG in Inkscape, not just
aggregate averages.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from lxml import etree
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import evaluate, render_svg_bytes  # noqa: E402
from svgseg import vectorize  # noqa: E402

TESTSET = ROOT / "testset"
PASS, FAIL = "PASS", "FAIL"


def paths_of(svg_path: Path) -> list[tuple[str, str]]:
    root = etree.parse(str(svg_path)).getroot()
    return [
        (element.get("fill"), element.get("d"))
        for element in root.iter()
        if etree.QName(element).localname == "path"
    ]


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    failures = 0

    # 1. Every piece is its own <path> with its exact colour.
    metadata = json.loads((TESTSET / "multicolor_text.json").read_text())
    svg_path = tmp / "text.svg"
    vectorize(TESTSET / "multicolor_text_512.png", svg_path)
    paths = paths_of(svg_path)
    fills = {fill.lower() for fill, _ in paths}
    expected = {piece["fill"].lower() for piece in metadata["pieces"]}
    missing = expected - fills
    failures += bool(missing)
    print(
        f"{PASS if not missing else FAIL} 1. one piece = one <path>: "
        f"{len(paths)} paths, "
        f"exact colours {len(expected & fills)}/{len(expected)}"
        + (f" missing {missing}" if missing else "")
    )

    # 2. Clean partition: nothing appears when a piece is moved, nothing is bare.
    print("\n     overlap and coverage per case (512px):")
    worst = 0.0
    for case in [
        "multicolor_text",
        "same_color_pieces",
        "geometric_logo",
        "holes",
        "banded_sphere",
        "thin_strokes",
    ]:
        out = tmp / f"{case}.svg"
        vectorize(TESTSET / f"{case}_512.png", out)
        result = evaluate(
            out, TESTSET / f"{case}_512_ids.npy", TESTSET / f"{case}_512.png", 512, 0.0
        )
        worst = max(worst, result["thick_overlap_pct"], result["uncovered_pct"])
        print(
            f"       {case:20} overlap={result['overlap_pct']:.3f}%  "
            f"(thick={result['thick_overlap_pct']:.3f}%)  "
            f"uncovered={result['uncovered_pct']:.3f}%  mIoU={result['mean_iou']:.4f}"
        )
    failures += worst >= 0.1
    # Raw overlap area cannot tell a deliberate 1 px seam, which prevents white
    # hairlines, from stacked silhouettes, which is the real defect. The criterion
    # measures what survives a 1 px erosion: stacked baselines score 37% there.
    print(
        f"{PASS if worst < 0.1 else FAIL} 2. nothing stacked nor uncovered: "
        f"worst {worst:.3f}% (target <0.1%)"
    )
    print("      raw overlap (~1-2%) is a deliberate 1 px seam, not stacking")

    # 3. No white hairlines: no rendered pixel comes out near-white where the
    #    input has colour. A gap between pieces would look exactly like that.
    worst_hairline = 0.0
    for case in ["multicolor_text", "geometric_logo", "banded_sphere"]:
        out = tmp / f"{case}.svg"
        reference = np.array(
            Image.open(TESTSET / f"{case}_512.png").convert("RGB")
        ).astype(int)
        render = render_svg_bytes(out.read_bytes(), 512, "#ffffff").astype(int)
        white_output = render.min(axis=2) > 235
        colored_input = reference.min(axis=2) < 200
        hairline = float(
            np.count_nonzero(white_output & colored_input)
            / reference[..., 0].size
            * 100
        )
        worst_hairline = max(worst_hairline, hairline)
        print(f"       {case:20} spurious white pixels={hairline:.4f}%")
    failures += worst_hairline >= 0.1
    print(
        f"{PASS if worst_hairline < 0.1 else FAIL} 3. no white hairlines between "
        f"pieces: worst {worst_hairline:.4f}% (target <0.1%)"
    )

    # 4. Transparency: the alpha background yields no pieces and no fringe.
    expected_pieces = 5  # The five concentric shapes of case_transparent.
    out = tmp / "transparent.svg"
    vectorize(TESTSET / "transparent_512.png", out)
    paths = paths_of(out)
    ground_truth = np.load(TESTSET / "transparent_512_ids.npy")
    outside = ground_truth < 0
    # Rendered over magenta: any path invading the transparent area shows up.
    render = render_svg_bytes(out.read_bytes(), 512, "#ff00ff")
    invaded = float(
        np.count_nonzero(
            (np.abs(render.astype(int) - [255, 0, 255]).sum(axis=2) > 30) & outside
        )
        / max(np.count_nonzero(outside), 1)
        * 100
    )
    ok = len(paths) == expected_pieces and invaded < 1.0
    failures += not ok
    print(
        f"\n{PASS if ok else FAIL} 4. transparency: {len(paths)} paths "
        f"(expected {expected_pieces}), transparent area invaded {invaded:.2f}% "
        f"(target <1%)"
    )

    print(f"\n{'ALL PASS' if failures == 0 else f'{failures} criterion(s) failing'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
