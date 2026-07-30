#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Check that an SVG is well formed and actually contains drawn paths.

CI used to assert this by grepping for ``<path``, which is wrong twice: the file
is serialized with a namespace prefix, so the literal string is ``<ns0:path``,
and a grep says nothing about whether the XML parses. Both are exactly the kind
of thing that would let a broken build pass.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("svg", type=Path)
    parser.add_argument(
        "--min-paths", type=int, default=1, help="fail below this many paths"
    )
    args = parser.parse_args()

    if not args.svg.is_file():
        print(f"{args.svg}: not written", file=sys.stderr)
        return 1

    try:
        root = ET.parse(args.svg).getroot()
    except ET.ParseError as error:
        print(f"{args.svg}: malformed XML: {error}", file=sys.stderr)
        return 1

    if root.tag != f"{{{SVG_NS}}}svg":
        print(f"{args.svg}: root element is {root.tag}, not svg", file=sys.stderr)
        return 1

    paths = root.findall(f".//{{{SVG_NS}}}path")
    filled = [p for p in paths if p.get("d") and p.get("fill")]
    if len(filled) < args.min_paths:
        print(
            f"{args.svg}: {len(filled)} filled paths, expected at least "
            f"{args.min_paths}",
            file=sys.stderr,
        )
        return 1

    print(
        f"{args.svg}: OK, {len(filled)} filled paths, {args.svg.stat().st_size} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
