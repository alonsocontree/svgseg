# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Tests for locating the potrace executable.

The frozen-build paths cannot be exercised on this machine, so what is tested is
the resolution order and, above all, that a failure names ``potrace``: the GUI
matches on that name to show an install hint instead of a raw traceback.
"""

from __future__ import annotations

import pytest

from svgseg import potrace


@pytest.fixture(autouse=True)
def _clear_cache():
    """The answer is cached, so each test needs a clean slate."""
    potrace.executable.cache_clear()
    yield
    potrace.executable.cache_clear()


def test_the_override_wins_over_the_path(tmp_path, monkeypatch):
    fake = tmp_path / "my-potrace"
    fake.write_text("")
    monkeypatch.setenv(potrace.ENV_VAR, str(fake))
    assert potrace.executable() == str(fake)


def test_an_override_pointing_nowhere_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv(potrace.ENV_VAR, str(tmp_path / "absent"))
    with pytest.raises(FileNotFoundError, match=potrace.ENV_VAR):
        potrace.executable()


def test_not_finding_it_names_potrace(monkeypatch):
    """worker.py matches on the name to offer an install hint."""
    monkeypatch.delenv(potrace.ENV_VAR, raising=False)
    monkeypatch.setattr(potrace.shutil, "which", lambda _name: None)

    with pytest.raises(FileNotFoundError) as caught:
        potrace.executable()
    assert caught.value.filename == "potrace"
    assert "potrace" in str(caught.value)


def test_falls_back_to_the_path(monkeypatch):
    monkeypatch.delenv(potrace.ENV_VAR, raising=False)
    monkeypatch.setattr(potrace.shutil, "which", lambda _name: "/usr/bin/potrace")
    assert potrace.executable() == "/usr/bin/potrace"


def test_a_frozen_build_prefers_its_own_copy(tmp_path, monkeypatch):
    """A one-file build unpacks into sys._MEIPASS and must look there first."""
    monkeypatch.delenv(potrace.ENV_VAR, raising=False)
    bundled = tmp_path / potrace.BINARY_NAME
    bundled.write_text("")
    monkeypatch.setattr(potrace.sys, "frozen", True, raising=False)
    monkeypatch.setattr(potrace.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(potrace.shutil, "which", lambda _name: "/usr/bin/potrace")

    assert potrace.executable() == str(bundled)


def test_nothing_is_bundled_when_not_frozen(monkeypatch):
    monkeypatch.setattr(potrace.sys, "frozen", False, raising=False)
    assert potrace._bundled_candidates() == []
