# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Translation loading and language switching.

Qt's own ``.ts`` format is used rather than gettext for one concrete reason: the
same mechanism also loads Qt's built-in translations, so the standard dialogs
("Open File", "Cancel", and so on) come out translated for free. With gettext
those would stay in English unless a second system were maintained alongside.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"

# The source language: its strings are the ones written in the code, so it has no
# .ts file of its own.
SOURCE_LANGUAGE = "en"

# Language names are deliberately written in their own language, which is what a
# reader looking for their own tongue expects to find.
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Espanol",
}

_SETTINGS_KEY = "language"


def available_languages() -> dict[str, str]:
    """Source language plus every language with a compiled ``.qm`` present."""
    languages = {SOURCE_LANGUAGE: LANGUAGE_NAMES[SOURCE_LANGUAGE]}
    for qm in sorted(TRANSLATIONS_DIR.glob("svgseg_*.qm")):
        code = qm.stem.removeprefix("svgseg_")
        languages[code] = LANGUAGE_NAMES.get(code, code)
    return languages


def settings() -> QSettings:
    return QSettings("svgseg", "svgseg")


def preferred_language() -> str:
    """The stored choice, else the system language, else the source language.

    The system locale decides on first run only. Once the user picks explicitly,
    that choice wins over the system for good.
    """
    stored = settings().value(_SETTINGS_KEY, "", type=str)
    languages = available_languages()
    if stored in languages:
        return stored
    for candidate in QLocale.system().uiLanguages():
        code = candidate.replace("_", "-").split("-")[0].lower()
        if code in languages:
            return code
    return SOURCE_LANGUAGE


def remember_language(code: str) -> None:
    settings().setValue(_SETTINGS_KEY, code)


class TranslationManager:
    """Installs and swaps the application and Qt translators at runtime."""

    def __init__(self, app) -> None:
        self._app = app
        self._app_translator = QTranslator(app)
        self._qt_translator = QTranslator(app)
        self._installed: list[QTranslator] = []

    def apply(self, code: str) -> None:
        for translator in self._installed:
            self._app.removeTranslator(translator)
        self._installed.clear()

        if code == SOURCE_LANGUAGE:
            # Nothing to install: the source strings are already English.
            return

        if self._app_translator.load(str(TRANSLATIONS_DIR / f"svgseg_{code}.qm")):
            self._app.installTranslator(self._app_translator)
            self._installed.append(self._app_translator)

        qt_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if self._qt_translator.load(f"qtbase_{code}", qt_dir):
            self._app.installTranslator(self._qt_translator)
            self._installed.append(self._qt_translator)
