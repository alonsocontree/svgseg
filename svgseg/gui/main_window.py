# svgseg - vectorize raster logos into editable SVG
# Copyright (C) 2026 Alonso Contreras
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. See the LICENSE file for the full text.
"""Main window.

Every visible string is set in :meth:`MainWindow.retranslate_ui` and nowhere else.
That is the discipline that makes switching language without restarting possible:
a string assigned outside that method would keep its original wording forever.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from svgseg.progress import (
    STAGE_LOAD,
    STAGE_QUANTIZE,
    STAGE_REGIONS,
    STAGE_TRACE,
    STAGE_WRITE,
)

from .preview import PreviewPanel
from .worker import VectorizeWorker, start_worker

IMAGE_FILTER_EXTENSIONS = "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"

# Images smaller than this are likely to have been downscaled already, and the
# thresholds scale with the pixel count, so the result loses fine detail. Measured:
# the same logo at 1024 px loses twice as much detail as at 2815 px.
SMALL_IMAGE_PX = 700


class MainWindow(QMainWindow):
    """Pick an image, tune a few parameters, convert, look at the result."""

    language_requested = Signal(str)

    def __init__(self, available_languages: dict[str, str], current: str) -> None:
        super().__init__()
        self._input: Path | None = None
        self._running = False
        # The status line is dynamic text. It is stored as (kind, values) rather
        # than as a formatted string so that retranslate_ui can rebuild it in the
        # new language; keeping the formatted string would freeze it in whatever
        # language it was produced in.
        self._status: tuple[str, dict] = ("start", {})
        # Both references are held until the thread reports finished; releasing
        # them earlier destroys a QThread that is still winding down.
        self._worker: VectorizeWorker | None = None
        self._thread: QThread | None = None
        self._languages = available_languages

        self.setAcceptDrops(True)
        self.resize(QSize(980, 660))

        self.preview = PreviewPanel()
        self._build_file_row()
        self._build_parameters()
        self._build_actions()
        self._build_menu(current)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(self.file_row)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.parameters_box)
        layout.addLayout(self.action_row)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        self.setCentralWidget(central)

        self.retranslate_ui()
        self._update_enabled()

    # --- construction -----------------------------------------------------

    def _build_file_row(self) -> None:
        self.input_label = QLabel()
        self.input_edit = QLineEdit()
        self.input_edit.setReadOnly(True)
        self.open_button = QPushButton()
        self.open_button.clicked.connect(self._choose_input)

        self.output_label = QLabel()
        self.output_edit = QLineEdit()
        self.output_button = QPushButton()
        self.output_button.clicked.connect(self._choose_output)

        self.file_row = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(self.input_label)
        top.addWidget(self.input_edit, 1)
        top.addWidget(self.open_button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.output_label)
        bottom.addWidget(self.output_edit, 1)
        bottom.addWidget(self.output_button)
        self.file_row.addLayout(top)
        self.file_row.addLayout(bottom)

    def _build_parameters(self) -> None:
        """Only the parameters that actually move the result.

        Each numeric one pairs with an Auto box, because the defaults are derived
        from image noise and overriding them blindly makes things worse.
        """
        self.parameters_box = QGroupBox()
        form = QFormLayout(self.parameters_box)

        self.delta_e_auto = QCheckBox()
        self.delta_e_auto.setChecked(True)
        self.delta_e_spin = QDoubleSpinBox()
        self.delta_e_spin.setRange(1.0, 40.0)
        self.delta_e_spin.setSingleStep(0.5)
        self.delta_e_spin.setValue(8.0)

        self.min_area_auto = QCheckBox()
        self.min_area_auto.setChecked(True)
        self.min_area_spin = QSpinBox()
        self.min_area_spin.setRange(1, 200_000)
        self.min_area_spin.setValue(4)

        self.min_length_auto = QCheckBox()
        self.min_length_auto.setChecked(True)
        self.min_length_spin = QSpinBox()
        self.min_length_spin.setRange(0, 500)
        self.min_length_spin.setValue(0)

        self.regularize_check = QCheckBox()
        self.regularize_check.setChecked(True)

        self.delta_e_row = self._auto_row(self.delta_e_spin, self.delta_e_auto)
        self.min_area_row = self._auto_row(self.min_area_spin, self.min_area_auto)
        self.min_length_row = self._auto_row(self.min_length_spin, self.min_length_auto)

        self.delta_e_caption = QLabel()
        self.min_area_caption = QLabel()
        self.min_length_caption = QLabel()
        self.regularize_caption = QLabel()
        form.addRow(self.delta_e_caption, self.delta_e_row)
        form.addRow(self.min_area_caption, self.min_area_row)
        form.addRow(self.min_length_caption, self.min_length_row)
        form.addRow(self.regularize_caption, self.regularize_check)

    def _auto_row(self, spin: QWidget, auto: QCheckBox) -> QWidget:
        auto.toggled.connect(lambda checked, widget=spin: widget.setDisabled(checked))
        spin.setDisabled(auto.isChecked())
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(spin)
        layout.addWidget(auto)
        layout.addStretch(1)
        return container

    def _build_actions(self) -> None:
        self.convert_button = QPushButton()
        self.convert_button.clicked.connect(self._convert)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setVisible(False)

        self.action_row = QHBoxLayout()
        self.action_row.addStretch(1)
        self.action_row.addWidget(self.cancel_button)
        self.action_row.addWidget(self.convert_button)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.status = QLabel()
        self.status.setWordWrap(True)

    def _build_menu(self, current: str) -> None:
        self.language_menu = self.menuBar().addMenu("")
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for code in self._languages:
            action = QAction(self)
            action.setCheckable(True)
            action.setChecked(code == current)
            action.triggered.connect(
                lambda _checked=False, chosen=code: self.language_requested.emit(chosen)
            )
            self.language_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

    # --- translation ------------------------------------------------------

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("svgseg - raster to editable SVG"))
        self.input_label.setText(self.tr("Image:"))
        self.output_label.setText(self.tr("Save to:"))
        self.open_button.setText(self.tr("Open image..."))
        self.output_button.setText(self.tr("Browse..."))
        self.input_edit.setPlaceholderText(self.tr("No image selected"))

        self.parameters_box.setTitle(self.tr("Parameters"))
        self.delta_e_caption.setText(self.tr("Colour separation:"))
        self.min_area_caption.setText(self.tr("Minimum piece area:"))
        self.min_length_caption.setText(self.tr("Keep thin strokes longer than:"))
        self.regularize_caption.setText(self.tr("Regularize geometry:"))
        for box in (self.delta_e_auto, self.min_area_auto, self.min_length_auto):
            box.setText(self.tr("Auto"))
        self.regularize_check.setText(
            self.tr("Straighten lines and fit circles and ellipses")
        )
        self.delta_e_spin.setToolTip(
            self.tr("Higher values merge similar colours, giving fewer pieces.")
        )
        self.min_area_spin.setToolTip(
            self.tr("Pieces smaller than this are absorbed into a neighbour.")
        )
        self.min_length_spin.setToolTip(
            self.tr(
                "A thin region longer than this is kept even if its area is tiny. "
                "0 disables the rule."
            )
        )

        self.convert_button.setText(self.tr("Convert"))
        self.cancel_button.setText(self.tr("Cancel"))
        self.language_menu.setTitle(self.tr("&Language"))
        for code, action in self.language_actions.items():
            action.setText(self._languages[code])

        self.preview.retranslate_ui()
        self._refresh_status()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.type() == event.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _set_status(self, kind: str, **values) -> None:
        self._status = (kind, values)
        self._refresh_status()

    def _refresh_status(self) -> None:
        kind, values = self._status
        if kind == "start":
            text = self.tr("Choose an image to begin.")
        elif kind == "ready":
            text = self.tr("Ready.")
        elif kind == "small":
            text = self.tr(
                "This image is small ({width}x{height}). Feeding the original, "
                "full-resolution file gives noticeably more detail."
            ).format(**values)
        elif kind == "stage":
            name = self._stage_name(values["stage"])
            if values["seconds_left"] < 0:
                text = name
            else:
                text = self.tr("{stage} - about {time} left").format(
                    stage=name, time=self._format_duration(values["seconds_left"])
                )
        elif kind == "cancelling":
            text = self.tr("Cancelling...")
        elif kind == "cancelled":
            text = self.tr("Cancelled.")
        elif kind == "done":
            text = self.tr(
                "Done: {pieces} pieces, {colors} colours. Saved to {path}"
            ).format(**values)
        elif kind == "potrace-missing":
            text = self.tr(
                "potrace was not found. svgseg needs it to trace outlines; "
                "install it with your package manager and try again."
            )
        elif kind == "failed":
            text = self.tr("Conversion failed: {error}").format(**values)
        else:
            text = ""
        self.status.setText(text)

    def _stage_name(self, stage: str) -> str:
        return {
            STAGE_LOAD: self.tr("Loading image"),
            STAGE_QUANTIZE: self.tr("Quantizing colours"),
            STAGE_REGIONS: self.tr("Finding pieces"),
            STAGE_TRACE: self.tr("Tracing outlines"),
            STAGE_WRITE: self.tr("Writing SVG"),
        }.get(stage, stage)

    # --- input ------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dropped_path(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        path = self._dropped_path(event)
        if path is not None:
            self._set_input(path)
            event.acceptProposedAction()

    @staticmethod
    def _dropped_path(event) -> Path | None:
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            suffix = path.suffix.lower().lstrip(".")
            if suffix and f"*.{suffix}" in IMAGE_FILTER_EXTENSIONS:
                return path
        return None

    def _choose_input(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Open image"),
            str(self._input.parent) if self._input else "",
            self.tr("Images ({extensions})").format(extensions=IMAGE_FILTER_EXTENSIONS),
        )
        if name:
            self._set_input(Path(name))

    def _choose_output(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save SVG"),
            self.output_edit.text(),
            self.tr("SVG files (*.svg)"),
        )
        if name:
            self.output_edit.setText(name)

    def _set_input(self, path: Path) -> None:
        self._input = path
        self.input_edit.setText(str(path))
        self.output_edit.setText(str(path.with_suffix(".svg")))
        self.preview.set_input(path)
        self.preview.clear_output()
        self._warn_if_small(path)
        self._update_enabled()

    def _warn_if_small(self, path: Path) -> None:
        from PySide6.QtGui import QImageReader

        size = QImageReader(str(path)).size()
        if size.isValid() and max(size.width(), size.height()) < SMALL_IMAGE_PX:
            self._set_status("small", width=size.width(), height=size.height())
        else:
            self._set_status("ready")

    def _update_enabled(self) -> None:
        running = getattr(self, "_running", False)
        self.convert_button.setEnabled(self._input is not None and not running)
        self.open_button.setEnabled(not running)
        self.output_button.setEnabled(not running)
        self.parameters_box.setEnabled(not running)

    # --- run --------------------------------------------------------------

    def _options(self) -> dict:
        return {
            "min_length": None
            if self.min_length_auto.isChecked()
            else self.min_length_spin.value(),
            "regularize": self.regularize_check.isChecked(),
        }

    def _convert(self) -> None:
        if self._input is None:
            return
        output = Path(self.output_edit.text()).expanduser()
        if not output.name:
            return

        self.preview.clear_output()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)

        self._running = True
        self._worker = VectorizeWorker(self._input, output, self._options())
        self._worker.progressed.connect(self._on_progress)
        self._worker.finished.connect(
            lambda info, path=output: self._on_finished(info, path)
        )
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._release_job)
        self._update_enabled()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self._set_status("cancelling")

    def _on_progress(self, stage: str, fraction: float, seconds_left: float) -> None:
        self.progress.setValue(int(fraction * 1000))
        self._set_status("stage", stage=stage, seconds_left=seconds_left)

    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return self.tr("{n} s").format(n=max(1, int(round(seconds))))
        minutes = int(seconds // 60)
        rest = int(round(seconds - minutes * 60))
        return self.tr("{m} min {s} s").format(m=minutes, s=rest)

    def _release_job(self) -> None:
        """Drop the worker and thread once the thread has really stopped."""
        self._worker = None
        self._thread = None

    def _finish_run(self) -> None:
        """Reset the UI. The worker and thread are released separately."""
        self._running = False
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        self._update_enabled()

    def _on_finished(self, info: dict, output: Path) -> None:
        self._finish_run()
        self.preview.set_output(output)
        self._set_status(
            "done", pieces=info["paths"], colors=info["colors"], path=str(output)
        )

    def _on_cancelled(self) -> None:
        self._finish_run()
        self._set_status("cancelled")

    def _on_failed(self, message: str) -> None:
        self._finish_run()
        if message == "potrace-missing":
            self._set_status("potrace-missing")
        else:
            self._set_status("failed", error=message)
        QMessageBox.warning(self, self.tr("Conversion failed"), self.status.text())

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Stop a running job so the process does not hang on exit."""
        if self._worker is not None:
            self._worker.cancel()
            if self._thread is not None:
                self._thread.quit()
                self._thread.wait(3000)
        super().closeEvent(event)


__all__ = ["MainWindow"]
