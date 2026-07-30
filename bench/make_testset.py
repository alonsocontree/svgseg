#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Generate the synthetic test set with ground truth.

For every case it writes, into testset/:

    <case>.svg              the reference vector source
    <case>_<px>.png         antialiased render: the vectorizer's input
    <case>_<px>_ids.png     id-coloured render, for visual inspection only
    <case>_<px>_ids.npy     the exact ground-truth label of every pixel
    <case>.json             metadata: pieces, colours, groups

The ground truth cannot be derived from an id-coloured render. With consecutive
ids, antialiasing between piece 0 and piece 8 produces values 1..7 which are
valid ids, contaminating the map with hundreds of phantom pixels without anyone
noticing, because the set of colours present is still the expected one. Instead
every piece is rasterized on its own in black and white and composited in z
order: thresholding at 50% gives exactly the semantics wanted, namely that a
pixel belongs to whoever covers most of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "testset"

CANVAS = 512  # The viewBox shared by every case.
SIZES = [128, 512, 2000]
BACKGROUND = "#ffffff"


def piece(element: str, fill: str, group: int) -> dict:
    """One visible ground-truth piece. ``element`` holds a {fill} placeholder."""
    return {"element": element, "fill": fill, "group": group}


# --- block letters, each one a single path ---------------------------------

GLYPHS = {
    "L": "M0,0 L20,0 L20,80 L60,80 L60,100 L0,100 Z",
    "T": "M0,0 L80,0 L80,20 L50,20 L50,100 L30,100 L30,20 L0,20 Z",
    "I": (
        "M0,0 L60,0 L60,20 L40,20 L40,80 L60,80 L60,100 L0,100 L0,80 "
        "L20,80 L20,20 L0,20 Z"
    ),
    "H": (
        "M0,0 L20,0 L20,40 L50,40 L50,0 L70,0 L70,100 L50,100 L50,60 "
        "L20,60 L20,100 L0,100 Z"
    ),
    "E": (
        "M0,0 L60,0 L60,20 L20,20 L20,40 L50,40 L50,60 L20,60 L20,80 "
        "L60,80 L60,100 L0,100 Z"
    ),
    "O": "M0,0 L70,0 L70,100 L0,100 Z M20,20 L20,80 L50,80 L50,20 Z",
}


def glyph(letter: str, x: float, y: float, scale: float, fill: str, group: int) -> dict:
    element = (
        f'<path transform="translate({x},{y}) scale({scale})" '
        f'fill-rule="evenodd" d="{GLYPHS[letter]}" fill="{{fill}}"/>'
    )
    return piece(element, fill, group)


# --- cases ----------------------------------------------------------------


def case_multicolor_text() -> list[dict]:
    """The stated use case: several letters, each in a different colour.

    A correct vectorizer yields one letter = one selectable ``<path>``.
    """
    colors = ["#e63946", "#2a9d8f", "#264653", "#e9c46a", "#8338ec"]
    letters = ["H", "O", "T", "E", "L"]
    out = []
    x = 40.0
    for index, (letter, color) in enumerate(zip(letters, colors, strict=True)):
        out.append(glyph(letter, x, 200, 1.6, color, group=index + 1))
        x += 100
    return out


def case_same_color_pieces() -> list[dict]:
    """Disjoint pieces sharing an exact colour.

    This is Inkscape multi-scan's characteristic failure: it puts all eight pieces
    into a single ``<path>`` with eight subpaths, so none can be selected alone.
    """
    out = []
    blue = "#1d3557"
    for index in range(5):
        cx = 80 + index * 90
        out.append(
            piece(
                f'<rect x="{cx - 30}" y="120" width="60" height="60" fill="{{fill}}"/>',
                blue,
                1,
            )
        )
    red = "#e63946"
    for index in range(3):
        cx = 120 + index * 140
        out.append(
            piece(f'<circle cx="{cx}" cy="340" r="45" fill="{{fill}}"/>', red, 2)
        )
    return out


def case_geometric_logo() -> list[dict]:
    """Straight edges, circles and right angles: exercises regularization."""
    return [
        piece('<circle cx="256" cy="256" r="180" fill="{fill}"/>', "#264653", 1),
        piece(
            '<rect x="146" y="146" width="220" height="220" fill="{fill}"/>',
            "#2a9d8f",
            2,
        ),
        piece('<path d="M256,180 L330,320 L182,320 Z" fill="{fill}"/>', "#e9c46a", 3),
        piece('<circle cx="256" cy="290" r="34" fill="{fill}"/>', "#e76f51", 4),
    ]


def case_holes() -> list[dict]:
    """Shapes with holes: a donut, a perforated square and two letter O shapes."""
    return [
        piece(
            '<path fill-rule="evenodd" d="M130,90 m-90,0 a90,90 0 1,0 180,0 '
            "a90,90 0 1,0 -180,0 M130,90 m-45,0 a45,45 0 1,0 90,0 "
            'a45,45 0 1,0 -90,0" fill="{fill}"/>',
            "#8338ec",
            1,
        ),
        piece(
            '<path fill-rule="evenodd" d="M290,20 L470,20 L470,200 L290,200 Z '
            'M340,70 L420,70 L420,150 L340,150 Z" fill="{fill}"/>',
            "#3a86ff",
            2,
        ),
        glyph("O", 60, 280, 1.8, "#fb5607", 3),
        glyph("O", 280, 280, 1.8, "#06d6a0", 4),
    ]


def case_thin_strokes() -> list[dict]:
    """Strokes 1 to 6 px wide on the base canvas: measures detail loss."""
    out = []
    colors = ["#111111", "#e63946", "#2a9d8f", "#3a86ff", "#fb8500", "#8338ec"]
    y = 60.0
    for index, thickness in enumerate([1, 2, 3, 4, 5, 6]):
        out.append(
            piece(
                f'<rect x="60" y="{y}" width="392" height="{thickness}" '
                f'fill="{{fill}}"/>',
                colors[index],
                index + 1,
            )
        )
        y += 42
    # Fine grid: 2 px verticals.
    for index in range(8):
        x = 70 + index * 52
        out.append(
            piece(
                f'<rect x="{x}" y="330" width="2" height="150" fill="{{fill}}"/>',
                "#111111",
                7,
            )
        )
    return out


def case_banded_sphere() -> list[dict]:
    """One object posterized into three flat colour bands.

    Geometrically these are three adjacent pieces, which exercises the white
    hairline problem, while semantically they form a single object.
    """
    return [
        piece('<circle cx="256" cy="256" r="170" fill="{fill}"/>', "#14213d", 1),
        piece('<circle cx="225" cy="225" r="120" fill="{fill}"/>', "#4361ee", 1),
        piece('<circle cx="200" cy="200" r="58" fill="{fill}"/>', "#a8dadc", 1),
    ]


def case_transparent() -> list[dict]:
    """Shapes over a TRANSPARENT background, with thin outlines between colours.

    This covers the alpha fringe: at the silhouette boundary the colour of a
    transparent PNG is a blend, and compositing it over white leaves a 1-2 px halo
    inside that turns into regions of its own. Without this case the bug went
    unnoticed (171 regions were measured where there are ~10, with 89 islands of a
    few pixels floating loose).
    """
    return [
        piece('<circle cx="256" cy="256" r="170" fill="{fill}"/>', "#ffffff", 1),
        piece('<circle cx="256" cy="256" r="158" fill="{fill}"/>', "#14213d", 1),
        piece('<circle cx="256" cy="256" r="96" fill="{fill}"/>', "#e63946", 2),
        piece('<circle cx="256" cy="256" r="84" fill="{fill}"/>', "#ffffff", 2),
        piece('<circle cx="256" cy="256" r="40" fill="{fill}"/>', "#2a9d8f", 3),
    ]


CASES = {
    "multicolor_text": case_multicolor_text,
    "same_color_pieces": case_same_color_pieces,
    "geometric_logo": case_geometric_logo,
    "holes": case_holes,
    "thin_strokes": case_thin_strokes,
    "banded_sphere": case_banded_sphere,
    "transparent": case_transparent,
}

# Cases whose background stays transparent instead of white.
NO_BACKGROUND = {"transparent"}


# --- SVG construction -----------------------------------------------------


def id_color(index: int) -> str:
    return f"#{0:02x}{index // 256:02x}{index % 256:02x}"


def build_svg(pieces: list[dict], ids: bool, with_background: bool = True) -> str:
    """Colour SVG (the input) or id SVG (for visual inspection only)."""
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS}" '
        f'height="{CANVAS}" viewBox="0 0 {CANVAS} {CANVAS}"'
    )
    head += ' shape-rendering="crispEdges">' if ids else ">"
    fill = id_color(0) if ids else BACKGROUND
    body = (
        [f'<rect x="0" y="0" width="{CANVAS}" height="{CANVAS}" fill="{fill}"/>']
        if with_background or ids
        else []
    )
    for index, item in enumerate(pieces, start=1):
        body.append(
            item["element"].format(fill=id_color(index) if ids else item["fill"])
        )
    return head + "".join(body) + "</svg>"


def build_piece_svg(item: dict) -> str:
    """A single piece in black on white: an unambiguous binary mask."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS}" '
        f'height="{CANVAS}" viewBox="0 0 {CANVAS} {CANVAS}">'
        f'<rect x="0" y="0" width="{CANVAS}" height="{CANVAS}" fill="#ffffff"/>'
        + item["element"].format(fill="#000000")
        + "</svg>"
    )


def build_id_map(
    pieces: list[dict], px: int, tmp: Path, opaque: bool = True
) -> np.ndarray:
    """Exact ground truth: each piece rasterized alone and composited in z order."""
    # With a transparent background there is no piece 0: that area is not
    # evaluated, and is marked -1 so the metrics exclude it rather than counting
    # it as uncovered.
    ids = np.zeros((px, px), np.int32) if opaque else np.full((px, px), -1, np.int32)
    for index, item in enumerate(pieces, start=1):
        source = tmp / f"_piece{index}.svg"
        target = tmp / f"_piece{index}.png"
        source.write_text(build_piece_svg(item))
        render(source, target, px)
        gray = np.asarray(Image.open(target).convert("L"))
        ids[gray < 128] = index
    return ids


def render(svg_path: Path, png_path: Path, px: int, opaque: bool = True) -> None:
    command = [
        "inkscape",
        str(svg_path),
        "--export-type=png",
        f"--export-filename={png_path}",
        f"--export-width={px}",
        f"--export-height={px}",
    ]
    if opaque:
        command += ["--export-background=#ffffff", "--export-background-opacity=1"]
    else:
        command += ["--export-background-opacity=0"]
    subprocess.run(command, check=True, capture_output=True)


def main() -> int:
    if not shutil.which("inkscape"):
        print("inkscape is not on the PATH", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    tmp = OUT / "_src"
    tmp.mkdir(exist_ok=True)

    index_entries = []
    for name, builder in CASES.items():
        pieces = builder()
        opaque = name not in NO_BACKGROUND
        color_svg = tmp / f"{name}.svg"
        ids_svg = tmp / f"{name}_ids.svg"
        color_svg.write_text(build_svg(pieces, ids=False, with_background=opaque))
        ids_svg.write_text(build_svg(pieces, ids=True))
        shutil.copy(color_svg, OUT / f"{name}.svg")

        visible = {}
        for px in SIZES:
            render(color_svg, OUT / f"{name}_{px}.png", px, opaque)
            render(ids_svg, OUT / f"{name}_{px}_ids.png", px)  # Inspection only.
            id_map = build_id_map(pieces, px, tmp, opaque)
            np.save(OUT / f"{name}_{px}_ids.npy", id_map)
            visible[px] = int(len(np.unique(id_map)))
            print(f"  {name}_{px}.png  visible pieces={visible[px]}")

        metadata = {
            "name": name,
            "canvas": CANVAS,
            "sizes": SIZES,
            # Piece 0 is the background; it counts as a piece because a correct
            # vectorizer must emit it too.
            "piece_count": len(pieces) + 1,
            "transparent_background": not opaque,
            # At 128 px some thin pieces really stop covering half a pixel and
            # vanish: the honest ground truth is this count.
            "visible_pieces": visible,
            "pieces": [{"id": 0, "fill": BACKGROUND, "group": 0}]
            + [
                {"id": i, "fill": item["fill"], "group": item["group"]}
                for i, item in enumerate(pieces, start=1)
            ],
        }
        (OUT / f"{name}.json").write_text(json.dumps(metadata, indent=2))
        index_entries.append({"name": name, "piece_count": metadata["piece_count"]})

    (OUT / "index.json").write_text(
        json.dumps({"sizes": SIZES, "cases": index_entries}, indent=2)
    )
    print(f"\n{len(CASES)} cases x {len(SIZES)} sizes -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
