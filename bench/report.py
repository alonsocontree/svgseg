#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Comparison table and contact sheet built from results/raw.json."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "results"
TESTSET = ROOT / "testset"

# (key, label, decimals, lower_is_better or None when not ranked)
COLUMNS = [
    ("mean_iou", "mIoU", 3, False),
    ("overlap_pct", "overlap%", 2, True),
    ("thick_overlap_pct", "thick%", 3, True),
    ("uncovered_pct", "uncovered%", 2, True),
    ("delta_e", "dE", 2, True),
    ("ssim", "SSIM", 4, False),
    ("paths", "paths", 0, None),
    ("total_nodes", "nodes", 0, True),
    ("seconds", "s", 2, True),
]


def _format(value, decimals: int) -> str:
    if value is None or (isinstance(value, float) and value != value):  # None or NaN
        return "-"
    return f"{value:.{decimals}f}" if decimals else f"{value:.0f}"


def table(rows: list[dict], title: str) -> str:
    valid = [row for row in rows if "error" not in row]
    if not valid:
        return f"\n{title}\n  (no valid rows)"

    headers = ["case", "px"] + [label for _, label, _, _ in COLUMNS]
    widths = [max(len("case"), *(len(row["case"]) for row in valid)), 5]
    widths += [max(len(label), 9) for label in headers[2:]]

    lines = [f"\n{title}", "-" * (sum(widths) + 2 * len(widths))]
    lines.append("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
    for row in sorted(valid, key=lambda row: (row["case"], row["px"])):
        cells = [row["case"].ljust(widths[0]), str(row["px"]).rjust(widths[1])]
        for (key, _, decimals, _), width in zip(COLUMNS, widths[2:], strict=True):
            cells.append(_format(row.get(key), decimals).rjust(width))
        lines.append("  ".join(cells))

    means = ["MEAN".ljust(widths[0]), "".rjust(widths[1])]
    for (key, _, decimals, _), width in zip(COLUMNS, widths[2:], strict=True):
        values = [row[key] for row in valid if isinstance(row.get(key), (int, float))]
        mean = sum(values) / len(values) if values else None
        means.append(_format(mean, decimals).rjust(width))
    lines.append("-" * (sum(widths) + 2 * len(widths)))
    lines.append("  ".join(means))
    return "\n".join(lines)


def contact_sheet(rows: list[dict]) -> str:
    """HTML page with the input and the output of every case side by side."""
    cases = sorted({row["case"] for row in rows})
    sizes = sorted({row["px"] for row in rows})

    def encode(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode()

    html = [
        "<meta charset='utf-8'><title>svgseg: synthetic test set</title>",
        "<style>body{font:13px system-ui;margin:20px;background:#fff;color:#111}"
        "table{border-collapse:collapse;margin-bottom:32px}"
        "td,th{border:1px solid #ddd;padding:4px;text-align:center;vertical-align:top}"
        "img,object{width:190px;height:190px;background:#fff;display:block}"
        "h2{margin:24px 0 8px}.meta{font:11px monospace;color:#555}</style>",
    ]
    for case in cases:
        html.append(
            f"<h2>{case}</h2><table><tr><th>px</th><th>input</th><th>output</th></tr>"
        )
        for px in sizes:
            png = TESTSET / f"{case}_{px}.png"
            svg = RESULTS / "svg" / f"{case}_{px}.svg"
            row = next(
                (r for r in rows if r["case"] == case and r["px"] == px),
                {},
            )
            html.append(f"<tr><td>{px}</td>")
            if png.exists():
                html.append(f"<td><img src='data:image/png;base64,{encode(png)}'></td>")
            else:
                html.append("<td class='meta'>missing</td>")
            if svg.exists() and "error" not in row:
                caption = (
                    f"mIoU {row.get('mean_iou', 0):.3f} - "
                    f"overlap {row.get('overlap_pct', 0):.2f}%<br>"
                    f"{row.get('paths', 0)} paths - {row.get('total_nodes', 0)} nodes"
                )
                html.append(
                    "<td><object type='image/svg+xml' data='data:image/svg+xml;base64,"
                    f"{encode(svg)}'></object><div class='meta'>{caption}</div></td>"
                )
            else:
                html.append(
                    f"<td class='meta'>{row.get('error', 'no output')[:60]}</td>"
                )
            html.append("</tr>")
        html.append("</table>")
    return "\n".join(html)


def main() -> int:
    raw = RESULTS / "raw.json"
    if not raw.exists():
        print(
            "results/raw.json is missing: run bench/run_synthetic.py", file=sys.stderr
        )
        return 1
    rows = json.loads(raw.read_text())

    print(table(rows, "SYNTHETIC TEST SET"))

    errors = [row for row in rows if "error" in row]
    if errors:
        print(f"\n{len(errors)} run(s) with errors:")
        for row in errors[:10]:
            print(f"  {row['case']:20} {row['px']:>5}  {row['error'][:90]}")

    out = RESULTS / "report.html"
    out.write_text(contact_sheet(rows))
    print(f"\ncontact sheet -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
