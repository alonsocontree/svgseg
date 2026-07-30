#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Run the vectorizer over the whole synthetic test set and score every output."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import evaluate  # noqa: E402
from svgseg import vectorize  # noqa: E402

TESTSET = ROOT / "testset"
RESULTS = ROOT / "results"


def run_one(case: str, px: int) -> dict:
    png = TESTSET / f"{case}_{px}.png"
    ground_truth = TESTSET / f"{case}_{px}_ids.npy"
    out_dir = RESULTS / "svg"
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / f"{case}_{px}.svg"

    row: dict = {"case": case, "px": px}
    try:
        started = time.perf_counter()
        vectorize(png, svg_path)
        elapsed = time.perf_counter() - started
        row.update(evaluate(svg_path, ground_truth, png, px, elapsed))
    except Exception as error:  # One bad case must not abort the whole run.
        row["error"] = f"{type(error).__name__}: {error}"
        row["traceback"] = traceback.format_exc()[-500:]
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="*", default=None)
    parser.add_argument("--px", nargs="*", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()

    index = json.loads((TESTSET / "index.json").read_text())
    cases = args.cases or [entry["name"] for entry in index["cases"]]
    sizes = args.px or index["sizes"]

    tasks = [(case, px) for case in cases for px in sizes]
    RESULTS.mkdir(exist_ok=True)
    print(f"{len(tasks)} runs: {len(cases)} cases x {len(sizes)} sizes\n")

    rows = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_one, *task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            row = future.result()
            rows.append(row)
            status = row.get(
                "error",
                f"mIoU={row.get('mean_iou', 0):.3f} "
                f"overlap={row.get('overlap_pct', 0):.2f}%",
            )
            print(f"[{done}/{len(tasks)}] {row['case']:20} {row['px']:>5}  {status}")

    rows.sort(key=lambda row: (row["case"], row["px"]))
    (RESULTS / "raw.json").write_text(json.dumps(rows, indent=2))
    print(f"\n-> {RESULTS / 'raw.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
