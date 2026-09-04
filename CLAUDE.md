# Working in this repo

`CONTRIBUTING.md` covers setup, layout, and how to run things. This file is the part that
is easy to get wrong.

## Branches and pull requests

Never commit to `main`. Branch first, short kebab-case name for the change itself
(`router-diagnostics`, not `fix` or a date).

Push the branch and open a PR with `gh pr create` when the work is ready — that is the
normal flow. **Merging, tagging and releasing are not**: releases are cut as GitHub
Releases and `publish.yml` uploads to PyPI over Trusted Publishing, so a tag is a publish.

The PR is the gate, because `ci.yml` runs on `pull_request`:

* `test` — Python 3.12/3.13/3.14 on Linux plus 3.13 on macOS; asserts the package has no
  runtime dependencies; fast suite with an 80% coverage floor; `pytest -m slow`
  uninstrumented; renders every board in `examples/`
* `lint` — `ruff check src tests tools`, then `mypy`
* `build` — wheel + sdist, `twine check`, and a check that the package data really ships

Run `pytest -m ''`, `ruff` and `mypy` locally first anyway. CI is slow to tell you.

## House rules for the code

**Write as though it had always been this way.** No tombstones: no "previously", "used
to", "no longer", no before-and-after commentary, no deprecated aliases or compatibility
shims left behind for their own sake.

**No issue numbers, PR links, commit hashes, or references to planning documents** —
`TODO.md`, a postmortem, a review — in code, docstrings, comments, or runtime messages.
Rationale that genuinely helps the next reader belongs in the docstring as a statement
about the present.

Citing the spec *is* expected, and the existing forms are `spec section 4.3` and
`SPEC 3.3 / rule 9`, where "rule N" means item N of `docs/router-spec.md` §8.

## Where a fact belongs

| | |
|---|---|
| `CHANGELOG.md` | What changed and why now. This is the only place the narrative lives. |
| `TODO.md` | Remaining work only. **Delete** an item when it ships — never strike it or mark it done. |
| `docs/router-notes.md` §6 | Open items are **struck through** when resolved (`~~**Name**~~ — resolved; ...`), not deleted. Local to that file. |
| `docs/router-spec.md` | Normative. If the code and the spec disagree, that is a finding to raise, not a licence to change either quietly. |

`CHANGELOG.md` style: H2 version with an ISO date, newest first, no `[Unreleased]`.
Present-tense declarative prose in multi-sentence paragraphs, not one-liners. ` -- ` for
em dashes (the docs use real em dashes; the changelog does not). Backticked symbols and
paths, concrete counts, no links.

Versions are single-sourced: `pyproject.toml` reads `stripboard.__version__`.

## The output is the product

Most of this library's behaviour *is* what it renders, and a PDF diff is unreadable. So
before touching anything under `src/`, capture a baseline:

```sh
python tools/capture_traces.py --boards examples --out .regression/before
# ... make the change
python tools/capture_traces.py --boards examples --out .regression/after
diff -r .regression/before .regression/after      # must be empty
```

Point `--boards` at private board designs as well — that is a far stronger net than
`examples/`, which has no high-fan-out net. It runs each board as a subprocess in its own
scratch directory, so it never writes into the design's own tree, and `.regression/` is
gitignored.

If a change is *meant* to alter output, say so in the commit message and the changelog,
and land it on its own commit.

## Things that bite

* **No runtime dependencies, ever.** CI asserts it. The PDF writer and the autorouter both
  ship in-package for this reason.
* `_state.py` declares only the surface the mixins share *across* modules — a method used
  solely within its own mixin does not belong there. Its docstring carries exact counts
  ("38 attributes and 65 methods"); keep them true if you add to it.
* `slow` marks the full place→route pipeline tests only, via a module-level `pytestmark`.
  Plenty of unmarked tests run the solver; `slow` is about the three-minute ones.
* Keep-out rects are **local, inclusive, integer** `(x0, y0, x1, y1)` offsets from the
  component origin. Negatives are legal and used.
* A cut occupies a whole hole, so two same-row strips need an empty hole between them —
  which means two different nets can never have pins in adjacent holes on one row.
* `jumper()`, `cut()` and `bus()` draw copper the autorouter cannot see. `link()` is the
  router-visible wire; there is currently no equivalent for a cut.

## Tests

Match what is there: a module docstring saying why the behaviour matters (usually in terms
of what breaks on a real board), test names as full sentences, `assert res.ok,
res.summary()` when the independent validator is the oracle. Reaching into privates is
normal here. No mocks — real objects and real solves on small boards.
