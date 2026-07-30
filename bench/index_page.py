#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Generate results/index.html: a single place to look at every result.

Results come out of several scripts and used to be scattered. This links them
together, rendering the thumbnails from the actual SVG files so what is shown is
the real output rather than a separately stored image.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import render_svg_bytes  # noqa: E402

RESULTS = ROOT / "results"


def _thumbnail(svg_path: Path, px: int = 300) -> str:
    array = render_svg_bytes(svg_path.read_bytes(), px, "#ffffff")
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _table(rows: list[dict], columns: list[tuple[str, str, str]]) -> str:
    header = "".join(f"<th>{label}</th>" for _, label, _ in columns)
    html = [f"<table><tr>{header}</tr>"]
    for row in rows:
        if "error" in row:
            continue
        cells = []
        for key, _label, spec in columns:
            value = row.get(key)
            cells.append(
                "<td>"
                f"{format(value, spec) if isinstance(value, int | float) else value}"
                "</td>"
            )
        html.append("<tr>" + "".join(cells) + "</tr>")
    html.append("</table>")
    return "".join(html)


def main() -> int:
    parts = [
        "<meta charset='utf-8'><title>svgseg: results</title>",
        "<style>body{font:14px/1.5 system-ui;margin:24px;max-width:1100px;color:#111}"
        "table{border-collapse:collapse;margin:8px 0 20px}"
        "td,th{border:1px solid #ddd;padding:4px 9px;text-align:right}"
        "th:first-child,td:first-child{text-align:left}"
        "th{background:#f5f5f5}h1{margin:0 0 4px}h2{margin:26px 0 6px}"
        ".gallery{display:flex;flex-wrap:wrap;gap:14px}"
        ".card{text-align:center;font:12px monospace}"
        "img{border:1px solid #ddd;background:#fff}a{color:#0057b8}"
        "p{color:#444}</style>",
        "<h1>svgseg results</h1>",
        "<p>Raster to SVG vectorizer where every piece is an editable "
        "<code>&lt;path&gt;</code>. Regenerate everything with "
        "<code>bench/run_synthetic.py</code>, <code>bench/report.py</code>, "
        "<code>bench/run_real.py</code>, <code>bench/crops.py</code> and "
        "<code>bench/verify.py</code>.</p>",
    ]

    native = sorted((RESULTS / "native").glob("*.svg"))
    if native:
        parts += [
            "<h2>Real logos, native resolution</h2>",
            "<p>This is how it should be used: the same logo reduced to 1024 px "
            "loses twice as much fine detail, because the thresholds scale with the "
            "pixel count.</p>",
            "<div class='gallery'>",
        ]
        for svg_path in native:
            kilobytes = svg_path.stat().st_size // 1024
            parts.append(
                f"<div class='card'><img width='300' src='data:image/png;base64,"
                f"{_thumbnail(svg_path)}'><br>"
                f"<a href='native/{svg_path.name}'>{svg_path.stem}.svg</a><br>"
                f"{kilobytes} KB</div>"
            )
        parts.append("</div>")

    real_raw = RESULTS / "real/raw.json"
    if real_raw.exists():
        parts += [
            "<h2>Real logo metrics (normalized to 1024 px)</h2>",
            "<p>Without ground truth there is no mIoU, but everything that decides "
            "whether the SVG is editable is still measurable. <b>detail%</b> is the "
            "error inside the fine-detail band, which is what SSIM does not see.</p>",
            _table(
                json.loads(real_raw.read_text()),
                [
                    ("logo", "logo", ""),
                    ("paths", "pieces", "d"),
                    ("total_nodes", "nodes", "d"),
                    ("colors", "colors", "d"),
                    ("detail_pct", "detail%", ".2f"),
                    ("p99_delta_e", "p99 dE", ".2f"),
                    ("overlap_pct", "overlap%", ".2f"),
                    ("ssim", "SSIM", ".4f"),
                    ("kilobytes", "KB", "d"),
                    ("seconds", "s", ".1f"),
                ],
            ),
        ]

    synthetic_raw = RESULTS / "raw.json"
    if synthetic_raw.exists():
        rows = sorted(
            json.loads(synthetic_raw.read_text()),
            key=lambda row: (row.get("case", ""), row.get("px", 0)),
        )
        parts += [
            "<h2>Synthetic test set, with ground truth</h2>",
            "<p>Seven cases at three sizes. Every piece is rasterized separately to "
            "get the exact label of each pixel; in <code>transparent</code> the alpha "
            "area is marked -1 and excluded from the metrics.</p>",
            _table(
                rows,
                [
                    ("case", "case", ""),
                    ("px", "px", "d"),
                    ("paths", "paths", "d"),
                    ("gt_pieces", "real pieces", "d"),
                    ("mean_iou", "mIoU", ".4f"),
                    ("overlap_pct", "overlap%", ".2f"),
                    ("thick_overlap_pct", "thick overlap%", ".3f"),
                    ("delta_e", "dE", ".2f"),
                    ("ssim", "SSIM", ".4f"),
                    ("total_nodes", "nodes", "d"),
                ],
            ),
        ]

    parts += [
        "<h2>Other views</h2><ul>",
        "<li><a href='crops.html'>crops.html</a> - magnified crops of the zones "
        "with the most error, chosen automatically. <b>Look at this before "
        "trusting an average</b>: SSIM moved three thousandths while the result "
        "looked clearly worse.</li>",
        "<li><a href='report.html'>report.html</a> - contact sheet of the synthetic "
        "test set, input and output side by side.</li>",
        "<li><code>svg/</code> - the synthetic test set outputs.</li>",
        "<li><code>real/svg/</code> - real logos normalized to 1024 px.</li>",
        "</ul>",
        "<p>Acceptance criteria: <code>python bench/verify.py</code></p>",
    ]

    out = RESULTS / "index.html"
    out.write_text("\n".join(parts))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
