"""`project()`: the whole per-board main block, in one call.

A board file is a ``draw(sb)`` function plus one ``project(...)`` call. Everything else --
the design-preview-versus-build-sheet toggle, the FRONT/BACK/DESIGN triptych, the label
PDF, the laser g-code, the carrier STL, the autoroute summary -- is scaffolding this
module owns.

The thing to know when writing a board file: ``draw`` is invoked **more than once**. Once
for a design preview; three times for the triptych; again on a fresh black-and-white
board for the label; again for the stroke capture that feeds the g-code. So ``draw``
should be a pure function of the board handed to it, and anything expensive inside it had
better be cached -- which is exactly what the autoroute solve cache does.
"""

from __future__ import annotations

from .board import StripBoard
from .geometry import parse_row as _rows

__all__ = ["project"]



def _label_render(draw, name, width, height, label):
    """Render the black-and-white label PDF (a fresh StripBoard, LABEL view)."""
    opts = {'name': label} if isinstance(label, str) else (label if isinstance(label, dict) else {})
    page = opts.get('page', (35.5,27.5))
    lw = opts.get('width', width)
    lh = opts.get('height', height)
    sb = StripBoard(page_width=page[0], page_height=page[1], black_and_white=True)
    sb.begin_view('LABEL', lw, lh, at=(0, 0), rotate=opts.get('rotate', False))
    draw(sb)
    sb.end_board()
    sb.gen(opts.get('name', f'{name}-label.pdf'))

def _carrier_render(sb, name, carrier):
    """Emit the 3D-printed carrier STL for the board last drawn on `sb`."""
    opts = {'name': carrier} if isinstance(carrier,
                                           str) else (carrier if isinstance(carrier, dict) else {})
    sb.gen_carrier(opts.get('name', f'{name}.stl'),
                  board_thickness=opts.get('board_thickness', 1.7),
                  nozzle=opts.get('nozzle', 0.4),
                  rotate=opts.get('rotate', False))

def _gcode_render(draw, name, width, height, gcode):
    """Render the LABEL view with stroke-capture on and write GRBL g-code (<name>.nc).

    Mirrors :func:`_label_render` but captures the LABEL strokes and serializes them for a
    laser. `gcode` is True, a filename str, or a dict; dict keys ``name``/``page``/``width``/
    ``height``/``rotate`` control the render and ``svg`` (bool or filename) also emits an SVG,
    while any remaining keys (``power``/``feed``/``passes``/``mirror``/``flip_y``/``dynamic``/
    ``frame``/``origin``/``pitch_mm``) pass straight to :meth:`StripBoard.gen_gcode`."""
    opts = dict(gcode) if isinstance(gcode,
                dict) else ({'name': gcode} if isinstance(gcode, str) else {})
    out = opts.pop('name', f'{name}.nc')
    page = opts.pop('page', (width + 14, _rows(height) + 2))
    lw = opts.pop('width', width)
    lh = opts.pop('height', height)
    rotate = opts.pop('rotate', False)
    svg = opts.pop('svg', False)
    sb = StripBoard(page_width=page[0], page_height=page[1], black_and_white=True)
    sb._cap_on = True
    sb.begin_view('LABEL', lw, lh, at=(0, 0), rotate=rotate)
    draw(sb)
    sb.end_board()
    sb.gen_gcode(out, **opts)
    if svg:
        sb.gen_svg(svg if isinstance(svg, str) else f'{name}.svg')

def project(draw, *, name, width, height,
            designing=True,
            pitch=None,
            y0=0,
            front_numbers=False,
            rotate=False,
            preview_page=None,
            build_page=None,
            label=False,
            carrier=False,
            gcode=False,
            builds=None,
            report=True):
    """One-call board driver: the whole per-project main block, encapsulated.

    ``draw(sb)`` is the single source of truth for the board -- it draws the components and
    either hand-routes them (``sb.jumper``/``sb.cut``/``sb.trace``) or declares nets and
    calls ``sb.autoroute()``. Everything else -- the DESIGN-vs-build toggle, the
    FRONT/BACK/DESIGN triptych, the label PDF, the carrier STL, and the autoroute report --
    is scaffolding this function owns, so a project file is just ``draw`` plus one call::

        project(draw, name='my-board', width=18, height='Z', label=True, carrier=True)

    Args:
      name:          output stem; writes ``<name>.pdf`` (and ``<name>-label.pdf`` / ``<name>.stl``).
      width, height: board size in holes; height is a row letter (``'Z'``) or an int.
      designing:     True -> one DESIGN-view page for fast iteration; False -> the build sheet
                     (triptych) plus optional label + carrier.
      pitch:         triptych column spacing (default ``width + 3``).
      y0, builds:    stacking controls; ``builds`` is a list of per-board dicts
                     (``{'y':.., 'tight':..}``) to place several boards on one sheet.
      front_numbers: print jumper lengths on the FRONT build view.
      preview_page / build_page: (w, h) page sizes; sensible defaults are derived from the
                     board size, override to match a hand-tuned canvas.
      label:         True, a filename str, or a dict of overrides (``name``/``page``/``width``/
                     ``height``/``rotate``) -> render the label PDF.
      carrier:       True, a filename str, or a dict (``name``/``board_thickness``/``nozzle``/
                     ``rotate``) -> emit the carrier STL.
      gcode:         True, a filename str, or a dict (``name``/``svg``/``power``/``feed``/
                     ``mirror``/``flip_y``/``frame``/...) -> render the LABEL silkscreen as
                     GRBL laser g-code (``<name>.nc``) for etching the board top.
      report:        print the autoroute summary if the board declared nets (no-op otherwise).

    Returns the primary StripBoard (its ``.last_result`` holds the routing, if any)."""
    if pitch is None:
        pitch = width + 3
    if preview_page is None:
        preview_page = (width + 12, _rows(height) + 10)
    if build_page is None:
        build_page = (pitch * 2 + width + 6, _rows(height) + 14)

    if designing:
        sb = StripBoard(page_width=preview_page[0], page_height=preview_page[1])
        sb.begin_view('DESIGN', width, height, at=(0, 0), rotate=rotate)
        draw(sb)
        sb.end_board()
        sb.gen(f'{name}.pdf')
    else:
        sb = StripBoard(page_width=build_page[0], page_height=build_page[1])
        for spec in (builds or [{}]):
            sb.triptych(draw, width, height, pitch=pitch,
                        y=spec.get('y', 0), y0=y0, tight=spec.get('tight', False),
                        front_numbers=front_numbers, rotate=rotate)
        sb.gen(f'{name}.pdf')
        if label:
            _label_render(draw, name, width, height, label)
        if carrier:
            _carrier_render(sb, name, carrier)

    # The laser g-code is the LABEL silkscreen rendered on its own fresh board, so it does
    # not depend on the DESIGN-vs-build toggle -- emit it in either mode (handy while you
    # are still iterating in `designing=True`).
    if gcode:
        _gcode_render(draw, name, width, height, gcode)

    if report:
        sb.route_report()
    return sb
