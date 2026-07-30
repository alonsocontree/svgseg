# svgseg

[![CI](https://github.com/alonsocontree/svgseg/actions/workflows/ci.yml/badge.svg)](https://github.com/alonsocontree/svgseg/actions/workflows/ci.yml)
[![Licence: GPL v3](https://img.shields.io/badge/licence-GPLv3-blue.svg)](LICENSE)

Vectorize raster logos into SVG where **every piece is a closed, disjoint,
selectable `<path>`** carrying its exact colour.

```bash
pip install svgseg
svgseg logo.png -o logo.svg
```

There is a graphical interface too:

```bash
pip install "svgseg[gui]"
svgseg-gui
```

On **Windows** there is nothing to install: download `svgseg.exe` from the
[latest release](https://github.com/alonsocontree/svgseg/releases/latest) and run
it. See [Install](#install) for the details, including the
[potrace](https://potrace.sourceforge.net/) dependency everywhere else.

## The problem

Inkscape's *Trace Bitmap* in multicolour mode (*Multiple scans -> Colors*) does
produce colour, but the result cannot be edited piece by piece:

- **Stacked layers rather than disjoint regions.** Each scan traces the full
  silhouette of everything above a threshold. Move one piece and the one beneath
  appears.
- **Every piece of the same colour lands in a single `<path>`** with subpaths, so
  none of them can be selected on its own.
- Halos and white hairlines from antialiasing.

Measured on the synthetic test set, Inkscape scores mIoU 0.170 on the
`same_color_pieces` case in both of its modes: it puts all eight disjoint pieces
into two paths, one per colour.

## The approach

The original idea was to solve this with semantic segmentation (SAM). Measurement
showed that in logos and icons the bottleneck **is not understanding the object,
it is edge handling**: antialiasing, piece shape and geometric regularization.
None of those three is improved by an AI model, so segmentation was tried,
measured and dropped. See *What was tried and did not stay*.

The result is an entirely classical, pixel-exact pipeline:

```
PNG/JPG
  |
  +-- [0] Preprocess      RGBA as stored, opacity mask kept separate
  +-- [1] Quantize        CIELAB palette + antialiasing matting     <- the core
  +-- [2] Regions         connected components -> partition
  +-- [3] Trace           potrace per region, selective dilation
  +-- [4] Regularize      lines, axes, circles and ellipses
  +-- [5] Assemble        one <path fill="#HEX"> per piece
```

### Stage 0: transparent PNG

A logo with a transparent background used to produce **171 regions where there
are ~10**. Two independent bugs, neither visible without a test case that has
alpha.

**Compositing over white corrupts the fringe.** PNG stores alpha
non-premultiplied, so each pixel's true colour is already in the file;
compositing with `rgb*a + (1-a)` dirties it exactly where alpha falls from 1 to 0
and leaves a whitish 1-2 px halo inside the silhouette, which later turns into
regions of its own. The RGB is now used as stored and the mask travels separately.

**Regions without a neighbour survived forever.** The speck filter merges each
small region into a neighbour, but a fringe island entirely surrounded by the
transparent area has none, and the loop simply skipped it: 89 of those 171
regions were islands of about 10 px floating loose, 0.005% of the total area
spread across 89 paths. A region below `min_area` that cannot be merged is now
discarded.

Everything that decides the palette is also restricted to the opaque pixels,
because otherwise the RGB of the transparent area, usually black or garbage,
invents colours that do not exist in the logo. Thresholds scale with the **opaque
area** rather than the canvas, since in a transparent PNG half the canvas may
have nothing to vectorize.

### Stage 1: why antialiasing is the main enemy

A logo PNG carries 1-2 px of blended pixels along every outline. Quantizing
naively turns that blend into new colours and creates a spurious sliver region
along **every** edge. It shows in the baseline: Inkscape's multi-scan on a
six-colour logo invents tones such as `#70a5a3` and `#9d63ee`, which are pure edge.

The method: classify every pixel as **pure** (locally constant neighbourhood) or
**mixed**; build the palette from the pure ones only, so antialiasing cannot
invent entries; and resolve every mixed pixel as a matting problem, finding the
pair of colours `(C1, C2)` present in its neighbourhood and the `alpha` that best
explains its colour as `alpha*C1 + (1-alpha)*C2`.

Each group's representative is an **exact** colour from the image rather than an
average, so the original hex value is preserved.

### Stage 2: what counts as a piece and what is noise

The speck filter is where two wrong decisions were made, and both are worth
recording.

**Filtering by area destroys detail.** With `min_area` calibrated to reduce the
piece count, the person in the `wash` logo collapses into a silhouette: the hand
merges into the overall and the white outline separating it from the torso
disappears. A 3 px outline is minuscule in area and essential in meaning.

**Colour contrast does not work as a criterion, and it is not a matter of
tuning.** It was tried and discarded: regions exist *precisely* where the
quantizer assigned different colours, so two adjacent regions always differ by
construction and the filter never fires. Measured: 2230 regions in the `wash`
logo where there should be ~70, for any `min_area` between 300 and 100000.
Comparing palette colours or original image colours makes no difference.

**A shape criterion exists, and it is off by default.** With `--min-length` a
region is absorbed only if it is small in area **and** compact, meaning its
longest side does not reach that value either: a 3x200 px outline survives on
length. That criterion makes `min_area` irrelevant, since with `min_length` fixed
any `min_area` between 300 and 100000 gives the same result.

| `min_length` | regions | detail lost% | p99 deltaE |
|---|---|---|---|
| **0 (default)** | 215 | 12.03 | 13.48 |
| 12 | 120 | 12.35 | 13.99 |
| 20 | 78 | 12.75 | 14.56 |
| 48 | 39 | 16.43 | 40.25 |

Compared visually on real logos, it stayed at **0**. With the shape criterion
enabled 2x to 5x more pieces appear (on one logo, 37 against 186) and the extra
pieces come out **jagged**: they are thin strokes that in an AI-upscaled image are
genuinely blurry, so tracing them produces noisy outlines. Some tiny detail is
lost, such as a car's side marker light, but for a logo a tidy outline is usually
preferable.

This is the only conclusion in the whole project that does **not** come from a
metric: the metric measures fidelity, and the input is blurry, so it rewards
reproducing the noise. For a logo you want idealization, not fidelity.

### Stage 3: the dilation rule

Tracing every region separately leaves sub-pixel gaps between neighbouring
pieces. The obvious fix, growing every mask by 1 px in all directions, has a
serious side effect: it turns a 1 px stroke into a 3 px one.

The correct rule: regions are painted from largest to smallest area, and **each
region grows only towards regions painted after it**. The large region then sits
underneath covering the seam, and the small one is drawn on top with its exact
outline. Thin strokes are never fattened because they only grow towards
neighbours smaller than themselves.

### Stage 4: geometric regularization

A traced outline follows the pixel staircase: a straight edge comes out with
micro-kinks and a circle comes out as dozens of wobbling curves. Four passes run
in [svgseg/geometry.py](svgseg/geometry.py):

| pass | what it does | tolerance |
|---|---|---|
| **straighten** | near-straight curves become lines, collinear lines merge | 0.35 px |
| **axes** | a near-horizontal or near-vertical line is aligned exactly | 0.6 px |
| **circles** | a subpath lying on a circle becomes 4 exact Beziers | 0.8 px |
| **ellipses** | otherwise a conic is fitted; if it is an ellipse, 4 exact Beziers | 0.8 px |

Measured over the 21 runs of the synthetic test set, paired:

| | mIoU | nodes | overlap% | deltaE | SSIM | KB |
|---|---|---|---|---|---|---|
| without regularization | 0.9421 | 126 | 2.472 | 0.195 | 0.9811 | 2.8 |
| **regularized** | 0.9426 | **81** | 2.506 | 0.187 | 0.9781 | **1.7** |
| change | +0.0005 | **-35%** | +0.03 | -0.009 | -0.003 | **-41%** |

35% fewer nodes and 41% less weight at no fidelity cost: mIoU ticks up and the
colour error goes down. On cases with circles the gain is larger, and there mIoU
**improves**, because an exact circle is closer to the truth than a wobbling trace.

Four details that were hard-won:

1. **Circle orientation is not optional.** potrace uses the nonzero fill rule and
   marks holes with reversed winding; emitting the circle backwards fills the
   hole. The sign of the original subpath's signed area is preserved.

2. **An endpoint cannot be moved on its own.** The coordinate is shared with the
   neighbouring segments, so aligning a line to an axis breaks the outline.
   Anchors that must share an X (or a Y) are grouped with union-find and each
   group is set to its mean, so a whole vertical wall ends up on a single X.

3. **The ellipse needs normalization before solving.** A general conic is fitted
   by least squares and the centre, semi-axes and rotation are extracted from the
   eigenvalues of its quadratic part. With unnormalised x^2 terms the system is
   ill-conditioned and the solution degrades at large image coordinates, so points
   are centred and scaled first.

4. **Relative output coordinates.** In absolute form an outline at 5841 px spends
   seven characters per number (`1536.25`) against three for the delta (`-50`).
   The first version emitted absolute coordinates and the file **grew** from 1158
   KB to 1427 KB despite having 20% fewer nodes. Rounding is measured against the
   already rounded position, not the ideal one, so it does not drift: 0.01 px
   maximum error over a chain of 400 points.

### Noise auto-tuning

A "flat colour" logo that went through an AI upscaler has no flat colour at all:
it arrives with tens of thousands of tones and soft edges. With values meant for a
clean render, one of the real logos fragmented into **3345 pieces** where there
are about 30.

The image *texture* is measured as the fraction of pixels with local variation,
which separates the three regimes cleanly:

| image type | texture |
|---|---|
| clean vector render | 0.01 - 0.05 |
| JPEG q75 | 0.18 |
| AI-upscaled logo | 0.16 - 0.70 |

`min_delta_e` and `min_area` follow from it. Raising `min_delta_e` not only
reduces the piece count, it also **improves** fidelity, because the palette stops
fitting noise (12 colours and SSIM 0.969 against 7 colours and SSIM 0.977 on the
same logo). Result on that case: 3345 -> 50 regions and 567.8 s -> 4.4 s.

The other change that made large images viable was **cropping each region to its
bounding box** before tracing. Dilating the whole image once per region is
O(regions x pixels); with thousands of regions at 2048 px that accounted for most
of those 567 seconds.

## Install

### Windows: one file, nothing to install

Download `svgseg-<version>-win64.exe` from the
[latest release](https://github.com/alonsocontree/svgseg/releases/latest) and run
it. It is the graphical interface, and it carries its own Python, Qt and potrace,
so there is nothing else to set up. Windows 10 or 11, 64-bit.

It is not code signed, so SmartScreen warns the first time: **More info** then
**Run anyway**. The `.zip` on the same release page holds the identical executable
plus every bundled licence, and the potrace source is attached there too.

For the command line on Windows, install with pip as below.

### Linux, macOS, and the command line

potrace is a separate program that svgseg runs, so install it first:

```bash
sudo apt install potrace     # Debian, Ubuntu
sudo dnf install potrace     # Fedora
brew install potrace         # macOS
```

Then:

```bash
pip install svgseg           # command line only
pip install "svgseg[gui]"    # and the graphical interface
```

If potrace ends up somewhere unusual, point at it with the `SVGSEG_POTRACE`
environment variable.

## Usage

```bash
python3 -m venv .venv
.venv/bin/pip install svgseg

svgseg logo.png -o logo.svg
svgseg logo.png -o logo.svg -v          # with diagnostics
```

Or from Python:

```python
from pathlib import Path
from svgseg import vectorize

info = vectorize(Path("logo.png"), Path("logo.svg"))
print(info["paths"], "pieces,", info["colors"], "colors")
```

**Feed it the native image, not a reduced one.** The same logo at 1024 px loses
twice as much fine detail as at 2815 px, because the thresholds scale with the
pixel count.

Options that move the result the most:

| option | what it does |
|---|---|
| `--min-delta-e` | minimum separation between palette colours (auto from noise) |
| `--min-area` | minimum piece area; below it the piece is absorbed (auto) |
| `--min-length` | a region whose longest side reaches this is kept for being thin and long |
| `--flat-tol` | local flatness threshold for treating a pixel as pure |
| `--alphamax` / `--opttolerance` | potrace curve parameters |
| `--line-tol` / `--axis-tol` / `--circle-tol` | per-pass regularization tolerances |
| `--no-regularize` | disable straightening and primitive fitting |

## Graphical interface

`svgseg-gui` wraps the same engine: drop an image in, see the input and the result
side by side, adjust the few parameters that matter, convert.

It is an **optional extra** because PySide6 weighs about 80 MB, which has no place
in a `pip install svgseg` for someone who only wants the command line. The core
package never imports Qt.

Two details worth knowing:

- **A progress bar with a time estimate.** The work takes between 0.6 s and 45 s
  depending on image size, so `vectorize()` accepts a `progress` callback and the
  window turns it into a bar plus a remaining-time figure. The estimate is rough at
  first and tightens as it goes, because the per-stage weights it rests on are
  approximate; the figure stays hidden until enough progress has accumulated to
  mean anything.
- **Cancelling needs no special API.** Raising from inside the `progress` callback
  unwinds the pipeline, and no output file is written.

The preview is rendered by Qt itself through `QSvgWidget`, so **the GUI does not
need Inkscape**. Inkscape remains a dependency of the measurement bench alone.

### Progress from your own code

```python
from pathlib import Path
from svgseg import vectorize


def report(stage: str, fraction: float) -> None:
    print(f"{stage}: {fraction:.0%}")


vectorize(Path("logo.png"), Path("logo.svg"), progress=report)
```

## Translations

The interface ships in English and Spanish. On first run it follows the system
language and falls back to English; the **Language** menu switches immediately,
without restarting, and remembers the choice.

Translating needs no Python: strings live in Qt `.ts` catalogues edited with Qt
Linguist. See **[docs/TRANSLATING.md](docs/TRANSLATING.md)** for the workflow and
for how to add a language.

`.ts` was chosen over gettext for a concrete reason: the same mechanism also loads
Qt's own translations, so the standard dialogs come out translated for free. With
gettext those would stay in English unless a second system were maintained.

## Results

### Real logos, native resolution

| logo | Mpx | pieces | colors | detail lost% | p99 deltaE |
|---|---|---|---|---|---|
| wash | 8.0 | 45 | 5 | 7.10 | 9.47 |
| bus | 33.7 | 97 | 11 | 8.64 | 9.08 |
| upscaled | 4.2 | 50 | 7 | 15.38 | 15.03 |

### Against the baselines (historical)

These numbers date from when the bench still ran vtracer and Inkscape over the
same four logos normalized to 1024 px. Those engines have been removed from the
project, so the table cannot be regenerated; it stands as evidence of why this
engine exists.

| engine | pieces | nodes | colors | detail% | p99 deltaE |
|---|---|---|---|---|---|
| **svgseg** | 32 | **1329** | **5** | **21.60** | **16.58** |
| vtracer (cutout) | 156 | 4727 | 142 | 21.75 | 18.97 |
| Inkscape (cutout) | 8 | 9801 | 8 | 41.30 | 33.26 |

What decides editability was not shape, which all three reproduce acceptably, but
**how many pieces and how many colours** the result carries. vtracer returned
**142 colours for a logo that has 5**: you cannot select "the orange" because
there are forty near-identical oranges. Inkscape left 8 giant paths, one per
colour, with every piece fused inside.

### Synthetic test set

Seven cases at three sizes, with exact ground truth.

| metric | value |
|---|---|
| mIoU | 0.943 |
| overlap% | 2.51 |
| thick overlap% | 0.000 |
| uncovered% | 0.00 |
| deltaE | 0.19 |
| SSIM | 0.9781 |
| nodes | 81 |

Raw overlap of ~2.5% is **entirely a deliberate 1 px seam**: eroding by 1 px
leaves 0.000%. The stacked modes of both baselines scored 39% of area with 37%
surviving erosion, which is genuine stacked silhouettes.

## Measurement bench

```bash
python bench/make_testset.py     # generates testset/ with ground truth
python bench/run_synthetic.py    # synthetic set, with ground truth
python bench/report.py           # table + results/report.html
python bench/run_real.py         # real logos, no ground truth
python bench/crops.py            # magnified crops -> results/crops.html
python bench/index_page.py       # results/index.html
python bench/verify.py           # acceptance criteria
```

The bench needs Inkscape as a **rasterizer** for the metrics
(`bench/inkscape_cli.py`); the vectorizer itself never uses it. It is kept even
though there are no rival engines left, because it is what catches a change that
makes the result worse, which is a mistake that was made twice here.

Before trusting an average, look at `results/crops.html`.

### Metrics

| metric | what it measures |
|---|---|
| **mIoU** | shape fidelity piece by piece, optimally matched against ground truth |
| **overlap%** | area where two shapes cover each other |
| **thick overlap%** | what survives a 1 px erosion: separates a harmless seam from stacking |
| **uncovered%** | holes in the output |
| **detail lost%** | error inside the fine-detail band, which SSIM does not see |
| **p99 deltaE** | 99th percentile of per-pixel error: the most sensitive to detail loss |
| **nodes** | editability: fewer nodes, easier to manipulate |
| **SSIM** | overall visual fidelity of the re-rendered SVG |

### Three measurement traps that were hard to find

All three produced plausible but false numbers, and they are worth keeping in mind
when touching the bench:

1. **Consecutive id colours contaminated by antialiasing.** The ground truth was
   derived from a render where piece *i* carried colour `#0000{i}`. Antialiasing
   between piece 0 and piece 8 produces blues 1..7, which are **valid ids**: every
   3600 px square had about 150 phantom pixels scattered across the image. The
   "no bleed" check did not catch it because it only verified that the *set* of
   colours present was the expected one. Fixed by rasterizing each piece
   separately in black and white and compositing in z order
   (`bench/make_testset.py:build_id_map`). On the output side, ids are spaced four
   apart per channel, rendering is supersampled and only exact matches are
   accepted (`bench/metrics.py:decode_ids`).

2. **SSIM does not see a face disappear.** Its value is dominated by large flat
   areas, so an engine can erase the fingers of a hand and move it three
   thousandths: it read 0.9638 for this engine against 0.9563 for vtracer while
   the result looked worse to the eye. The measure that does catch it looks only
   at the *detail band* (small colour components plus a 2 px strip along every
   edge), where the bad case jumps from 12.03% to 24.01% error, with p99 deltaE
   going from 13.48 to 74.45. See `detail_band` in `bench/metrics.py`, and
   `bench/crops.py` for the magnified crops, which is what to look at before
   believing an average.

3. **The node counter was wrong.** It counted command letters, but SVG allows
   implicit repetition: `l0 -50 70 0 70 0` is ONE `l` command with three segments.
   potrace uses it heavily, so the real count was underestimated by roughly 500x.
   With the counter fixed, a node advantage that had been reported as 16x turned
   out to be 3.6x on real images and a tie on the synthetic set.

## Development

```bash
pip install -e ".[gui,dev]"
pytest                  # 54 tests, no display and no Inkscape needed
ruff check . && ruff format --check .
```

The test suite covers what runs without external tools: path parsing and
emission, circle and ellipse fitting, winding preservation, connected components
and the speck filter, palette recovery and noise estimation, progress reporting,
locating the potrace binary, and the translation catalogues.

Two of those catch failures that are easy to miss by eye: that a `progress`
callback changes not one byte of the output, and that no translated string has lost
a `{placeholder}`, which would otherwise raise in front of the user.

### Continuous integration

[`ci.yml`](.github/workflows/ci.yml) runs ruff and the tests on Linux, macOS and
Windows. The matrix is not ceremony: the pipeline shells out to potrace and builds
paths by hand, so a Windows-only assumption has to fail there and not in someone's
install. Since the tests deliberately need no Qt,
[`packaging/gui_smoke_test.py`](packaging/gui_smoke_test.py) covers what they
cannot -- that the window constructs and survives a language change -- headlessly
under Qt's offscreen platform plugin.

### Building the Windows executable

[`windows-release.yml`](.github/workflows/windows-release.yml) does it on a tag
push (`v1.2.3`) or on demand, with PyInstaller and
[`packaging/windows/svgseg.spec`](packaging/windows/svgseg.spec). It downloads the
official potrace win64 binary, verifies a pinned SHA-256, freezes everything into
one `svgseg.exe`, and then **runs that executable's `--selftest`**: it converts a
bundled example and fails the build unless real paths come out. A successful
freeze proves nothing on its own, because a library not surviving the freeze only
shows up at run time.

To build it locally, from a Windows checkout:

```
set SVGSEG_POTRACE_EXE=C:\path\to\potrace.exe
pip install ".[gui]" pyinstaller
pyinstaller --noconfirm --clean packaging/windows/svgseg.spec
dist\svgseg.exe --selftest
```

The spec is not Windows-specific, so the same two commands on Linux produce a
working one-file binary. That is worth knowing: it is how the spec gets tested
without waiting on a Windows runner.

## What was tried and did not stay

Four things were implemented, measured and removed. The code is gone; the
measurements are kept because the lesson is worth more than the code.

**SAM segmentation.** Tried in two distinct roles. Grouping regions into `<g>` per
object worked well, and arbitrating which small region is a real piece worked too:
with an aggressive geometric filter it rescued 15 pieces and brought p99 deltaE
down from 40 to 20. But being conservative with the filter beat being aggressive
plus rescue (72 pieces and p99 14.72 against 54 and 19.94), and it was 10x faster.
MobileSAM's ONNX encoder also has a trap: it declares dynamic axes and accepts any
size without complaining, yet only produces valid embeddings at 1024x1024. At
native size it returned garbage masks, IoU 0.31 against 0.99.

**Sub-pixel outline correction.** The matting alpha gives the true edge position,
and using it brought the placement error down from 0.5 px to 0.083 px. It still
did not pay off: the only thing that improved was overlap (2.506% -> 2.383%),
which was already known to be a harmless 1 px seam, and on real logos it was
negative, pushing nodes from 45271 to 47307 and detail lost from 8.31% to 8.64%.
The premise was false: at these resolutions the grid error already sits below the
noise floor of colour quantization.

**Colour-contrast speck filter.** It cannot work, and it is not a matter of
tuning: regions exist precisely where the quantizer assigned different colours, so
two adjacent regions always differ by construction and the filter never fires
(2230 regions where there should be ~70, for any `min_area`).

**Supersampling before tracing.** Enlarging the map before tracing improved mIoU
(0.967 -> 0.998) and overlap (1.58% -> 0.15%), but with the broken node counter
its cost was invisible: it multiplied nodes by 9x to 57x (one case went from 57 to
3271) in exchange for +0.005 mIoU. `opttolerance` has no influence at all; that
was measured too.

## Still open

Fitting **rounded rectangles**, which show up often in logos. It requires
detecting four straight sides plus four corner arcs and checking they share a
radius, considerably more fragile than fitting a conic to a whole outline.

**Ellipses** are implemented and validated against known ellipses, but their
benefit is not demonstrated because the test set contains none. A synthetic case
with ellipses would be worth adding before trusting that branch.

## Licence

GPL-3.0-or-later, see [LICENSE](LICENSE).

The reason is potrace, which is GPL-2.0-or-later. The source tree only ever
invokes it as a subprocess, and running a separate program is not a derivative
work, so the code itself could be under a permissive licence. **The Windows
release bundles `potrace.exe` inside the executable**, and distributing a GPL
program as part of a larger whole puts the whole under the GPL. Rather than have
the licence depend on which artefact you downloaded, the whole project is GPL.

What that means in practice: you may use, study, modify and redistribute this,
including commercially, as long as you pass on the same freedoms and publish your
source changes under the GPL.

The Windows release ships potrace's own licence and a written offer for its
source alongside the executable, which is what the GPL requires of a
redistributor. potrace is by Peter Selinger, <https://potrace.sourceforge.net/>.
