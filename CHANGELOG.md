# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-06

### Changed
- Continuous integration runs one job where it ran four. The matrix covered Python 3.12,
  3.13 and 3.14 on Linux plus 3.13 on macOS, which is a great deal of wall clock for a
  package with no runtime dependencies and no platform-specific code; `test` is now Python
  3.14 on Linux alone, and `lint` and `build` move to 3.14 with it so that every job
  agrees on an interpreter. `requires-python` stays at `>=3.12` and the classifiers are
  unchanged, so 3.12 and 3.13 remain supported -- they are simply no longer verified on
  every push.
- `dev` is the default branch and the branch pull requests target. `main` holds released
  commits only, and `publish.yml` is the one thing that writes to it.
- Releasing is a single workflow run. `publish.yml` takes the version as a required input
  and, in order, fast-forwards `main` onto `dev`, tags that commit, cuts the GitHub
  Release with notes taken from this file, and uploads to PyPI over Trusted Publishing.
  The upload comes last because it is the only step of the four that cannot be taken back.
  Four checks run against `dev` before any of them move: `stripboard.__version__` has to
  equal the input exactly, no `v<version>` tag may already exist, the version has to be
  newer than every tag that does, and this file has to carry the matching section. A
  release that forgets the version bump fails in front of the upload rather than spending
  a version number on PyPI.

## [0.2.0] - 2026-09-04

### Added
- The router says why a net did not route. Every failure used to read `no collision-free
  route found`; a net now carries the geometry that defeated it. `row_conflicts` is a
  placement-only check for the failures that need no search at all -- a net's strip on a
  row has to cover its own outermost pins there and put its track cuts on the columns
  immediately outside them, so a foreign pin anywhere in that reach is fatal whatever the
  topology, jumper column or detour row. Those nets are named precisely and are no longer
  searched for, which also removes them from all sixty rip-up attempts.
- `explain_net(board, instances, netlist, net_id)` routes one net on its own and reports
  the feasibility the search worked from: the columns in which a jumper could bridge each
  pair of the net's rows, and -- for a pair with none -- what occupies every column. Pass
  a solved `Routing` and every other net's copper joins the obstacles, which answers which
  net took the column this one needed; leave it out and the net meets the parts alone,
  which answers whether it could route on this placement at all. `sb.explain(net_id)`
  prints it for a board. This closes the last open item in `docs/router-notes.md` §6.
- `UnroutableNetWarning`, raised by `autoroute()` for each net it could not route, so a
  half-wired board is loud without reading the report. Like the other design-rule
  warnings it can be escalated: `warnings.simplefilter('error', StripboardWarning)` makes
  an unroutable board fail the build.
- `sb.link(x, y1, y2)` places a wire by hand that the autorouter routes around -- its two
  ends are pins, so `handle.pin('1')` joins a net like any other part's, and the span
  between them is a keep-out. `jumper()`, `cut()` and `bus()` draw copper the solver
  cannot see, so mixing them with `autoroute()` was a silent collision risk with no
  supported alternative.
- `sb.route_report(verbose=True)` adds what you need in front of the board: every net's
  jumpers with their lengths, the total wire end to end, and which cuts are buried under a
  part body and so have to be made first. `sb.cuts_under_bodies()` returns that last set.
- `sb.stepstick()`, the 2x8 stepper-driver carrier, with `variant='a4988'` or
  `'tmc2209'` for the pin names and a body keep-out for the socket. It is the first
  builder to carry both named pins and a keep-out; `dip()`, `sip()` and `xiao()` still
  register pins only.
- `feasible_columns` and `steiner_row_candidates` are now part of the router's surface,
  since the diagnostics answer the same questions the search does.

### Changed
- Pin order is documented where it is used. `dip()` and `sip()` state how a `pins` list is
  consumed, `resist()` states that pin `'1'` is the top hole and what `upside_down` swaps,
  and `docs/coordinates.md` says it once for all of them. Previously the DIP order was
  written down only on a private helper and the SIP order nowhere at all.
- `cut()` is documented. An integer column drills the hole out and splits that row's
  track, which is the form the autorouter emits; a half-column such as `7.5` severs the
  track between two columns and leaves both holes usable. Neither form was written down,
  and `docs/coordinates.md` described the half-column behaviour on an integer call.
- `docs/coordinates.md` states that a cut costs a whole hole, so two different nets cannot
  have pins in adjacent holes on one row. That follows from `docs/router-spec.md` §3.3 and
  has always been enforced, but it was discoverable only by having a net fail.
- `keepout()`'s docstring said shading was the default when the default is `show=False`.
- `xiao()`'s comment named the RP2040 board specifically; the pin map fits the family.

## [0.1.1] - 2026-09-03

### Changed
- Package author metadata is now `Stocko` rather than a personal name. This is the
  `Author` field PyPI shows under *Credits*; 0.1.0 keeps the old value, since a published
  version's metadata is immutable.
- The version is declared in one place. `pyproject.toml` reads it from
  `stripboard.__version__` via setuptools' `dynamic` version support, so a release cannot
  ship a package whose `__version__` disagrees with its distribution metadata.

## [0.1.0] - 2026-09-03

First public release.

### Added
- `StripBoard` is now a facade composed from mixins, one module per concern (`canvas`,
  `text`, `footprints/*`, `wiring`, `connectivity`, `netlist`, `autoroute`, `export`),
  replacing a single 2200-line module holding a 112-method class. Every method kept its
  name and signature. `_state.py` declares the state and cross-mixin methods they share
  -- 38 attributes and 65 methods -- so a type checker can follow the composition and the
  coupling is written down rather than implicit.
- The data tables (the vector stroke font, the colour palettes, the view presets) moved
  into `font.py`, `palette.py` and `views.py` and are now built once at import instead of
  being rebuilt on every `StripBoard`. Affine transform maths moved to `transform.py`,
  shared by the PDF emitter and the g-code stroke capture that has to stay in step with
  it.
- Continuous integration: the full suite on Python 3.12-3.14 plus macOS, `ruff`, `mypy`,
  a wheel build, and a gate asserting the package still has no runtime dependencies.
- A test suite of 535 tests. The default selection runs in about 2.5 seconds; the four
  solver-heavy router tests are marked `slow` and the OpenSCAD one `integration`.
- `tools/capture_traces.py`, the regression harness: it renders a directory of board
  scripts and reduces each artifact to a normalized trace (a PDF's page content streams
  with structure and metadata stripped; g-code and SVG verbatim). Point it at your own
  designs for a much stronger safety net than the examples alone provide -- `.regression/`
  is gitignored, so private boards never enter the repository.
- First packaged release of a library that previously lived as a single
  `stripboard.py` script: `pip install stripboard`, a `stripboard` console script, and a
  real test suite.
- The autorouter is now bundled as `stripboard.router` and needs no separate install.
  `autoroute()` no longer manipulates `sys.path` at runtime to find it.

### Changed
- **The PDF backend is now built in**, replacing the PyFPDF (`fpdf` 1.7.2) dependency.
  The package has **no runtime dependencies at all**. Rendered output is unchanged: for a
  corpus of 33 board variants, every drawing operator in every page content stream is
  byte-identical before and after the swap. The one difference anywhere in the streams is
  a single trailing newline that PyFPDF emitted before `endstream`, which PDF ignores as
  whitespace. PDF output is now also deterministic, since nothing stamps the current time
  into the document.

- Design-rule diagnostics are now real warnings (`JumperConflictWarning`,
  `ShortCircuitWarning`, `TraceCollisionWarning`, all under `StripboardWarning`) instead
  of bare `print()` calls. They are visible by default, carry the offending board file's
  location, can be escalated with `-W error::stripboard.drc.StripboardWarning`, and are
  assertable in tests.
- `gen_carrier()` locates `Carrier.scad` as package data rather than by absolute path,
  resolves `openscad` on `PATH`, passes its arguments as a list (so paths with spaces
  work), and raises a clear error when the binary is missing or exits non-zero. It
  previously discarded both the output and the exit status.
- Exporters accept `pathlib.Path`, create missing parent directories, and write UTF-8
  explicitly. `project()` output still lands in the working directory.
- The g-code header comment now reads `generated by stripboard` rather than naming a
  script file. **This changes the first line of generated `.nc` files** and is the only
  intentional output difference in this release.

### Fixed
- `dot_grid()` raised `TypeError`: `page_width`/`page_height` are floats (they are divided
  by `scale`) and reached `range()` untruncated. Every call site in the wild was commented
  out as a result.
- `esp32minikit(x, y)` ignored both coordinates -- its footprint was pinned to hardcoded
  positions -- and drew its left header twice from two byte-identical lines.
- `bus(x, y1, y2)` rejected row letters, and `range(y1, y2 - 1)` dropped the last link so
  the final strip in the span was never tied in. It also now draws a single continuous
  wire soldered at each crossing, which is how a bus is actually built; the previous
  ladder of separate jumpers put two wire ends in holes that only take one.
- Mutable default arguments (`skip_pins=[]`) on `dip`, `xiao` and the DIP renderer.
- `draw_letter()` raised a bare `KeyError` for any character absent from the built-in
  stroke font, so one stray character in a label aborted the whole render. It now warns
  (`MissingGlyphWarning`) and skips that character.
- Warning locations point at the board file that caused them, at whatever call depth --
  the stack level is discovered rather than hardcoded, since `jumper()` and `text()` sit
  different distances from the check that fires.

### Known issues
- `trace_point()` is a recursive flood fill that rescans its connection list per cell, so
  it is O(cells x connections) and can approach the recursion limit on a large board.
