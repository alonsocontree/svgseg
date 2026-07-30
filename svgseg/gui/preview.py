# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Before and after preview.

The output is shown with ``QSvgWidget``, so Qt rasterizes the SVG itself. That is
why the GUI needs no Inkscape: Inkscape remains a dependency of the measurement
bench alone.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Checkerboard so transparent areas read as transparent rather than as white.
_CHECKER = (
    "background-color: #ffffff;"
    "background-image:"
    " linear-gradient(45deg, #e6e6e6 25%, transparent 25%),"
    " linear-gradient(-45deg, #e6e6e6 25%, transparent 25%),"
    " linear-gradient(45deg, transparent 75%, #e6e6e6 75%),"
    " linear-gradient(-45deg, transparent 75%, #e6e6e6 75%);"
)


class _RasterView(QLabel):
    """Shows a bitmap scaled to fit while keeping its aspect ratio."""

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._source: QPixmap | None = None

    def set_image(self, path: Path | None) -> None:
        self._source = None if path is None else QPixmap(str(path))
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source is None or self._source.isNull():
            self.clear()
            return
        self.setPixmap(
            self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class _Pane(QWidget):
    """One titled preview pane holding either a placeholder or the content."""

    def __init__(self, content: QWidget) -> None:
        super().__init__()
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder = QLabel()
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet("color: #777;")

        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(content)
        self.stack.setStyleSheet(_CHECKER)
        self.stack.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.stack, 1)

    def show_content(self, visible: bool) -> None:
        self.stack.setCurrentIndex(1 if visible else 0)


class PreviewPanel(QWidget):
    """Input bitmap on the left, produced SVG on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.raster = _RasterView()
        self.svg = QSvgWidget()
        # Without this the SVG is stretched to fill the widget, so a circle shows
        # up as an oval and the preview misrepresents the result.
        self.svg.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.svg.setMinimumSize(160, 160)
        self.svg.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self.input_pane = _Pane(self.raster)
        self.output_pane = _Pane(self.svg)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.input_pane, 1)
        layout.addWidget(self.output_pane, 1)

        self.retranslate_ui()

    def set_input(self, path: Path | None) -> None:
        self.raster.set_image(path)
        self.input_pane.show_content(path is not None)

    def set_output(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.output_pane.show_content(False)
            return
        self.svg.load(str(path))
        # load() replaces the renderer contents, so the mode is reapplied.
        self.svg.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.output_pane.show_content(True)

    def clear_output(self) -> None:
        self.set_output(None)

    def retranslate_ui(self) -> None:
        self.input_pane.title.setText(self.tr("Input"))
        self.output_pane.title.setText(self.tr("Result"))
        self.input_pane.placeholder.setText(
            self.tr("Drop an image here, or use Open image")
        )
        self.output_pane.placeholder.setText(self.tr("The SVG will appear here"))
