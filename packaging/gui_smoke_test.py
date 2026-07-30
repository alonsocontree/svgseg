#!/usr/bin/env python3
# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Build the window headlessly and switch every language, then exit.

This is not in ``tests/`` on purpose: the test suite deliberately needs no Qt and
no display, so it stays fast and installable without the GUI extra. This script
covers what those tests cannot -- that the window actually constructs and that
``retranslate_ui()`` survives a language change -- and runs under the offscreen
platform plugin, so it needs no display either.

Run it with ``QT_QPA_PLATFORM=offscreen python packaging/gui_smoke_test.py``.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from svgseg.gui.i18n import TranslationManager, available_languages
from svgseg.gui.main_window import MainWindow


def main() -> int:
    app = QApplication([])
    translations = TranslationManager(app)
    languages = available_languages()
    if "en" not in languages:
        print("the source language is missing", file=sys.stderr)
        return 1

    window = MainWindow(languages, "en")
    window.show()

    for code in languages:
        translations.apply(code)
        window.retranslate_ui()
        title = window.windowTitle()
        if not title:
            print(f"{code}: the window title came back empty", file=sys.stderr)
            return 1
        print(f"  {code}: {title}")

    app.processEvents()
    print(f"OK, {len(languages)} languages: {', '.join(languages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
