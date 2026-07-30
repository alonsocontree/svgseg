# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Translation catalogue tests.

They only read the .ts and .qm files, so they need neither Qt nor a display and
run in CI. What they protect is the thing that silently rots: a string added to
the code and never translated.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

TRANSLATIONS = Path(__file__).resolve().parent.parent / "svgseg/gui/translations"
CATALOGUES = sorted(TRANSLATIONS.glob("svgseg_*.ts"))


def test_at_least_one_catalogue_exists():
    assert CATALOGUES, "expected svgseg_es.ts at minimum"


@pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda p: p.stem)
def test_every_string_is_translated(catalogue):
    """A missing or unfinished translation leaves the UI half English."""
    tree = ET.parse(catalogue)
    untranslated = []
    for message in tree.findall(".//message"):
        translation = message.find("translation")
        source = (message.find("source").text or "").strip()
        missing = translation is None or not (translation.text or "").strip()
        if missing or translation.get("type") == "unfinished":
            untranslated.append(source)
    assert not untranslated, f"untranslated in {catalogue.name}: {untranslated[:5]}"


@pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda p: p.stem)
def test_placeholders_survive_translation(catalogue):
    """A dropped {name} placeholder raises KeyError at runtime, in the user's face."""
    import re

    pattern = re.compile(r"\{(\w+)\}")
    tree = ET.parse(catalogue)
    for message in tree.findall(".//message"):
        source = message.find("source").text or ""
        translation = message.find("translation")
        translated = (translation.text or "") if translation is not None else ""
        assert set(pattern.findall(source)) == set(pattern.findall(translated)), (
            f"placeholder mismatch in {catalogue.name}: {source!r} -> {translated!r}"
        )


@pytest.mark.parametrize("catalogue", CATALOGUES, ids=lambda p: p.stem)
def test_compiled_catalogue_exists_and_is_newer(catalogue):
    """The wheel ships .qm, not .ts, so a stale .qm means stale translations."""
    compiled = catalogue.with_suffix(".qm")
    assert compiled.exists(), f"run pyside6-lrelease on {catalogue.name}"
    assert compiled.stat().st_mtime >= catalogue.stat().st_mtime - 1, (
        f"{compiled.name} is older than its source; run pyside6-lrelease again"
    )
