# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- First packaged release of a library that previously lived as a single
  `stripboard.py` script: `pip install stripboard`, a `stripboard` console script, and a
  real test suite.
- The autorouter is now bundled as `stripboard.router` and needs no separate install.
  `autoroute()` no longer manipulates `sys.path` at runtime to find it.

### Changed
- **The PDF backend is now built in**, replacing the PyFPDF (`fpdf` 1.7.2) dependency.
  The package has **no runtime dependencies at all**. Rendered output is unchanged: the
  page content streams for a corpus of 33 board variants are byte-identical before and
  after the swap. PDF output is now also deterministic, since nothing stamps the current
  time into the document.

### Fixed
- Nothing yet in this release; see the notes on `dot_grid`, `esp32minikit` and `bus`
  below for known issues being addressed.

### Known issues
- `dot_grid()` raises `TypeError` (a float reaches `range()`).
- `esp32minikit(x, y)` ignores its coordinates and draws its footprint twice.
- `bus(x, y1, y2)` rejects row letters and drops its last jumper.
- `trace_point()` is a recursive flood fill that rescans its connection list per cell, so
  it is O(cells x connections) and can approach the recursion limit on a large board.
