# Contributing

## Setup

```sh
pip install -e ".[dev]"
```

Python 3.12 or newer. There are no runtime dependencies and there should not be any —
if you find yourself wanting one, please open an issue first.

## Project layout

```
src/stripboard/
  __init__.py       public API re-exports
  board.py          StripBoard -- the facade the mixins below compose into
  project.py        project(), the one-call driver a board file uses
  component.py      the handle a part builder returns
  _state.py         the state and methods the mixins share (type-checking only)

  canvas.py         drawing primitives, colours, the transform stack
  text.py           the four text orientations
  footprints/       part builders, grouped by kind
  wiring.py         jumpers, hand-placed links, cuts, drills, keep-outs
  connectivity.py   trace(): flood-fill a net to check it
  netlist.py        net() and connect()
  autoroute.py      driving the router and drawing its result
  export/           PDF, g-code, SVG, carrier STL

  font.py           the vector stroke font
  palette.py        colour tables
  views.py          the FRONT/BACK/DESIGN/LABEL presets
  geometry.py       row-letter coercion
  transform.py      affine matrix maths
  pdf/              the built-in PDF writer
  router/           the bundled autorouter
  cli.py            the `stripboard` console script
```

`StripBoard` is a facade composed from mixins rather than a set of collaborating objects.
That is deliberate: these methods share a great deal of genuinely mutable render state --
the PDF document, the transform stack, the `show_*` toggles, the connection list, the
solve cache -- and `_state.py` writes that shared surface down. Shrinking it is the path
to a cleaner decomposition, if one is wanted.

## Tests

```sh
pytest                  # fast suite; solver tests are deselected
pytest -m ''            # everything
pytest -m slow          # only the solver/render tests
ruff check src tests tools
mypy
```

Tests marked `slow` run the autorouter, which takes seconds per solve. Tests marked
`integration` need an external binary (OpenSCAD) and skip when it is absent.

## Not changing the rendered output by accident

Most of this library's behaviour *is* its output, and a PDF diff is unreadable. So the
regression net compares **normalized page content streams** — every drawing operator,
colour change and transform, in order, with document structure and metadata stripped.
`tools/capture_traces.py` renders a directory of board scripts and writes one trace per
artifact:

```sh
# capture a baseline before you start
python tools/capture_traces.py --boards examples --out .regression/before

# ...make your change, then
python tools/capture_traces.py --boards examples --out .regression/after
diff -r .regression/before .regression/after
```

Point `--boards` at your own board designs for a much stronger net — the more boards, the
more of the drawing surface gets exercised. `.regression/` is gitignored, so private
designs never end up in the repository.

If a change is *meant* to alter output, say so in the commit message and in the changelog,
and land it on its own rather than mixed in with a refactor.

## Style

`ruff` and `mypy` configuration lives in `pyproject.toml`. The public API is fully typed;
internal helpers are looser on purpose.
