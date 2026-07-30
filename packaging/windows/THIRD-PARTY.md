# What is inside svgseg.exe

`svgseg.exe` is a self-contained build: it carries a Python interpreter, the
libraries svgseg depends on, and potrace. That is why it needs nothing installed,
and also why this file exists -- everything bundled keeps its own licence.

## svgseg

Copyright (C) 2026 Alonso Contreras. GPL-3.0-or-later, see `LICENSE.txt`.
Source: <https://github.com/alonsocontree/svgseg>

## potrace

By Peter Selinger, <https://potrace.sourceforge.net/>. GPL-2.0-or-later.

svgseg does the segmentation and colour work; potrace turns each region's
pixel mask into a smooth outline. It is bundled as `potrace.exe` inside the
executable and invoked as a subprocess.

Under `potrace/` you will find its licence (`COPYING.txt`), its authors, and
**its complete unmodified source** as `potrace-1.16.tar.gz`. The binary is the
official win64 build published by the potrace project, downloaded and verified
against a pinned SHA-256 checksum at build time; see
`.github/workflows/windows-release.yml`.

## Python libraries

Bundled by PyInstaller and each under its own licence:

| Library | Licence |
| --- | --- |
| Python | PSF |
| NumPy | BSD-3-Clause |
| SciPy | BSD-3-Clause |
| scikit-image | BSD-3-Clause |
| Pillow | MIT-CMU |
| OpenCV (headless) | Apache-2.0 |
| lxml | BSD-3-Clause |
| PySide6 / Qt | LGPL-3.0 |

Qt is used under the LGPL. The GUI links it dynamically and the Qt libraries are
shipped unmodified, so replacing them is possible; the way to do that is to
install svgseg from source with `pip install svgseg[gui]`, which uses the PySide6
wheels from PyPI directly.
