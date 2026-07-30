# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Command line interface.

svgseg logo.png -o logo.svg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .pipeline import vectorize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="svgseg",
        description=(
            "Vectorize a raster image into an SVG where every piece is an "
            "editable <path>. Requires potrace on the PATH."
        ),
    )
    parser.add_argument("input", type=Path, help="input image (PNG, JPEG, ...)")
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="output SVG path"
    )
    parser.add_argument("--version", action="version", version=f"svgseg {__version__}")

    palette = parser.add_argument_group("palette")
    palette.add_argument("--max-colors", type=int, default=32)
    palette.add_argument(
        "--min-delta-e",
        type=float,
        default=None,
        help="minimum separation between palette colours (auto from noise)",
    )
    palette.add_argument(
        "--flat-tol",
        type=float,
        default=4.0,
        help="local flatness threshold for treating a pixel as pure",
    )

    pieces = parser.add_argument_group("pieces")
    pieces.add_argument(
        "--min-area",
        type=int,
        default=None,
        help="minimum piece area; below it the piece is absorbed (auto)",
    )
    pieces.add_argument(
        "--min-length",
        type=int,
        default=None,
        help=(
            "a region whose longest side reaches this is kept for being thin and "
            "long (auto, default 0)"
        ),
    )
    pieces.add_argument("--connectivity", type=int, default=8, choices=[4, 8])

    curves = parser.add_argument_group("curves")
    curves.add_argument(
        "--alphamax", type=float, default=1.0, help="potrace corner threshold"
    )
    curves.add_argument(
        "--opttolerance", type=float, default=0.2, help="potrace curve tolerance"
    )
    curves.add_argument(
        "--no-regularize",
        action="store_true",
        help="do not straighten lines nor fit circles and ellipses",
    )
    curves.add_argument(
        "--line-tol",
        type=float,
        default=0.35,
        help="deviation in px for treating a curve as a line",
    )
    curves.add_argument(
        "--axis-tol",
        type=float,
        default=0.6,
        help="deviation in px for snapping a line to the axes",
    )
    curves.add_argument(
        "--circle-tol",
        type=float,
        default=0.8,
        help="deviation in px for replacing an outline with a circle or ellipse",
    )

    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    info = vectorize(
        args.input,
        args.output,
        max_colors=args.max_colors,
        min_delta_e=args.min_delta_e,
        flat_tol=args.flat_tol,
        min_area=args.min_area,
        min_length=args.min_length,
        connectivity=args.connectivity,
        alphamax=args.alphamax,
        opttolerance=args.opttolerance,
        regularize=not args.no_regularize,
        line_tol=args.line_tol,
        axis_tol=args.axis_tol,
        circle_tol=args.circle_tol,
    )
    if args.verbose:
        for key, value in info.items():
            rendered = f"{value:.2f}" if isinstance(value, float) else str(value)
            print(f"  {key}: {rendered}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
