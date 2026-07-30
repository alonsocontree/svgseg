# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Assembly of the final SVG.

One ``<path>`` per piece. Each one carries its own transform only when tracing
could not return it to pixel coordinates; with regularization enabled, which is
the default, paths come out untransformed.
"""

from __future__ import annotations

from lxml import etree

from .tracing import Shape

SVG_NS = "http://www.w3.org/2000/svg"


def build_svg(shapes: list[Shape], width: int, height: int) -> bytes:
    root = etree.Element(
        f"{{{SVG_NS}}}svg",
        attrib={
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "version": "1.1",
        },
    )
    group = etree.SubElement(root, f"{{{SVG_NS}}}g")
    for shape in shapes:
        path = etree.SubElement(group, f"{{{SVG_NS}}}path")
        path.set("fill", shape.fill)
        if shape.transform:
            path.set("transform", shape.transform)
        path.set("d", shape.d)
    return etree.tostring(
        root, xml_declaration=True, encoding="utf-8", pretty_print=True
    )
