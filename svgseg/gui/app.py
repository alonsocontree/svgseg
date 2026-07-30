# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Entry point of the graphical interface: ``svgseg-gui``."""

from __future__ import annotations

import sys


def _missing_pyside_message() -> str:
    return (
        "svgseg-gui needs PySide6, which is not installed.\n"
        "Install it with:\n\n"
        "    pip install 'svgseg[gui]'\n"
    )


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        # A bare ImportError traceback would be useless to someone who just wants
        # the app, so the actionable command is printed instead.
        print(_missing_pyside_message(), file=sys.stderr)
        return 1

    from svgseg import __version__

    from .i18n import (
        TranslationManager,
        available_languages,
        preferred_language,
        remember_language,
    )
    from .main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("svgseg")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("svgseg")

    translations = TranslationManager(app)
    languages = available_languages()
    language = preferred_language()
    translations.apply(language)

    window = MainWindow(languages, language)

    def switch(code: str) -> None:
        remember_language(code)
        translations.apply(code)
        # Qt posts a LanguageChange event to every widget, which the window turns
        # into a retranslate_ui() call.
        window.retranslate_ui()

    window.language_requested.connect(switch)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
