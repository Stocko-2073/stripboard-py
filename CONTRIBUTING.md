# Contributing

## Setup

```sh
pip install -e ".[dev]"
```

Python 3.12 or newer. There are no runtime dependencies and there should not be any —
if you find yourself wanting one, please open an issue first.

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
