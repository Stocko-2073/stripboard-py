"""Design stripboard (protoboard) circuit layouts in Python.

Write a ``draw(sb)`` function that places components on the hole grid and either routes
them by hand (``jumper``/``cut``/``trace``) or declares a netlist and calls
``autoroute()``; then hand it to :func:`project`, which renders the board PDF and any
label, laser g-code or carrier you ask for.

    from stripboard import project

    def draw(sb):
        sb.text(1, 'A', 'HELLO')
        sb.led(4, 'C')

    project(draw, name='hello', width=12, height='K')

Coordinates are a 1-based integer grid: columns are numbers along ``x``, rows are letters
(``'A'`` == 1 ... ``'Z'`` == 26) or ints along ``y``. Copper strips run horizontally, so
two pins on the same row start out connected.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

from .font import VECTOR_CHARS
from .palette import COLORS, WIRE_COLORS
from .views import VIEW_PRESETS
from . import transform

from .drc import (
    JumperConflictWarning,
    MissingGlyphWarning,
    ShortCircuitWarning,
    StripboardWarning,
    TraceCollisionWarning,
)
from .drc import warn as _warn
from .pdf import PdfDocument

__version__ = "0.1.0"

# Bezier control-point ratio for approximating a quarter circle: 4 * ((sqrt(2) - 1) / 3).
KAPPA = 0.5522848

__all__ = [
    "Component",
    "StripBoard",
    "project",
    "StripboardWarning",
    "JumperConflictWarning",
    "ShortCircuitWarning",
    "TraceCollisionWarning",
    "MissingGlyphWarning",
    "__version__",
]


class Component:
    """Handle returned by a StripBoard part builder (``xiao``/``dip``/``sip``/...).

    Carries the part's pin holes in *world* coordinates so the autorouter can build a
    footprint from the exact geometry the renderer drew (one source of truth), plus a
    redraw closure so an unlocked (auto-placed) part can be rendered where the solver
    placed it. Existing callers that ignore the return value are unaffected.

    Pins are addressed by name via :meth:`pin`, which returns the ``(instance_id,
    local_id)`` reference the netlist uses -- e.g. ``sb.net('WS', mic.pin('WS'), ...)``.
    """

    def __init__(self, id, pins, origin, locked=True, keepouts=(), internal=(), redraw=None):
        self.id = id
        self.pins = dict(pins)              # name -> world (x, y) hole
        self.origin = origin                # (x, y) world of the draw call
        self.locked = locked
        self.keepouts = tuple(keepouts)     # local rects as (x0, y0, x1, y1) tuples
        self.internal = tuple(internal)     # tuple[frozenset[str]] of internally-tied pins
        self._redraw = redraw               # callable(origin, flipped) -> None (deferred draw)

    def pin(self, name):
        """Return the ``(instance_id, name)`` netlist reference for pin ``name``.

        Numeric pins may be given as an ``int`` for convenience -- e.g.
        ``c1.pin(2)`` is equivalent to ``c1.pin('2')``.
        """
        if isinstance(name, int):
            name = str(name)
        if name not in self.pins:
            raise KeyError(
                f"Component {self.id!r} has no pin {name!r}; available: {sorted(self.pins)}"
            )
        return (self.id, name)

    def __repr__(self):
        return f"Component({self.id!r}, pins={sorted(self.pins)}, locked={self.locked})"


class StripBoard:
    """A board being drawn: geometry, components, wiring, and the PDF it renders to.

    One instance is a whole *sheet*, not a single board -- ``begin_board``/``end_board``
    bracket each board on it, and ``triptych`` puts three views of the same board side by
    side. See :func:`project` for the usual entry point.
    """

    # Shared data tables (see font.py, palette.py, views.py). Class-level so they are
    # built once at import rather than rebuilt per instance.
    vector_chars = VECTOR_CHARS
    colors = COLORS
    wire_colors = WIRE_COLORS
    _VIEW_PRESETS = VIEW_PRESETS

    def __init__(
        self,
        offset_x=2.0,
        offset_y=2.0,
        scale=1.0,
        show_traces=True,
        show_numbers=False,
        show_crosses=True,
        show_jumpers=True,
        show_components=True,
        page_width=110,
        page_height=85,
        black_and_white=False
    ):
        # --- laser/g-code path capture (additive side-channel; off by default) ---
        # When _cap_on is True the geometry primitives ALSO record their stroked paths,
        # transformed by _cap_ctm (a CTM stack that mirrors the PDF transform operators),
        # into _cap_paths. gen_gcode()/gen_svg() serialize that. PDF output is unaffected.
        # Set up before the base page transforms below (they call _scale/_flip_y/_translate,
        # which touch _cap_ctm); begin_board() resets _cap_ctm so those base ops drop out
        # and captured coordinates stay in board-grid (hole) units.
        self._cap_on = False
        self._cap_paths = []                                # list[list[(x, y)]], grid units
        self._cap_ctm = [transform.IDENTITY]                 # stack of affine (a,b,c,d,e,f)

        self.black_and_white = black_and_white
        self.page_width = page_width / scale
        self.page_height = page_height / scale
        # 7.2 pt per board unit: page_* are tenths of an inch at 72 pt/inch. Derived from
        # the raw arguments, not the /scale-adjusted self.page_* set just above.
        self.pdf = PdfDocument(width_pt=page_width * 7.2, height_pt=page_height * 7.2)
        self.pdf.add_page()
        self._out('1 J 1 j')  # Set line cap and join styles
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.rotate = False

        self._scale(7.2 * scale)
        self._flip_y()
        self._translate(0,-self.page_height)
        self.line_width(.2)
        self.show_numbers = show_numbers
        self.show_traces = show_traces
        self.show_crosses = show_crosses
        if not show_crosses: self.show_traces = False
        self.show_jumpers = show_jumpers
        self.show_components = show_components
        # Autoroute solve cache: persists across begin_board() so the same board rendered
        # in multiple views (FRONT/BACK/DESIGN) is solved once, then drawn per view.
        self._route_cache = {}
        self._router = None  # the autorouter module, resolved on first use (see _ensure_router)
        self.last_result = None  # set by autoroute(); read by route_report()/project()
        self.black()

    def dot_grid(self):
        """Stipple the whole page with a 1-unit dot grid, as a layout aid."""
        self.line_width(0.1)
        # page_width/page_height are floats (they are divided by `scale`), so they have
        # to be truncated before they can bound a range.
        for y in range(1, int(self.page_height)):
            for x in range(1, int(self.page_width)):
                self._line(x, y, x, y)

    def origin_mark(self):
        self.red()
        self._out('%.2F %.2F m %.2F %.2F l S' % (-1,-1, 1,1))
        self._out('%.2F %.2F m %.2F %.2F l S' % (-1,1, 1,-1))
        self.black()

    def title(self, x, y, text):
        self.show_components = True
        self.flip_x = False
        self._push()
        self._translate((self.page_width-len(text)*1.5)/2+x,4+y)
        self._scale(1.5)
        self.text(0,0,text.upper())
        self._pop()

    def parts_list(self,x,y,parts):
        self.show_components = True
        self.show_crosses = True
        self.flip_x = False
        self._push()
        width = 0
        height = len(parts) * 1.5 + 6
        for p in parts:
            width = max(width, len(p))
        width += 1
        self._translate((self.page_width-width)/2+x, (self.page_height-height)/2+y)
        self.black()
        self.text(1,0,'PARTS LIST')
        self.text(1.05,0,'PARTS LIST')
        self.wire(0,1,width,1)
        y = 2
        for p in parts:
            self.text(1,y,p.upper())
            y += 1.5
        self.cut(1,int(y+1))
        self.text(3,int(y+1),"= CUT TRACE")
        self._pop()

    def begin_board(
        self, board_width, board_height, 
        rotate=False, 
        at=(0,0),
        show_strips=True, 
        show_traces=True,
        show_numbers=False,
        show_crosses=True,
        show_jumpers=True,
        show_components=True,
        show_drills=True,
        show_coordinates=True,
        flip_x=False,
        title=""
    ):
        self.show_numbers = True
        self.show_traces = True
        self.show_crosses = True
        self.show_jumpers = True
        self.show_components = True
        self.show_strips=True
        self.flip_x = False
        self.show_coordinates = show_coordinates

        self.connections = []
        self.trace_origins = []
        self.nc_points = []
        self.trace_color = 0
        # Per-view autoroute accumulators: rebuilt each time the board's draw lambda runs.
        self._route_components = []   # list[Component] registered by the part builders
        self._route_nets = []         # list[(net_id, frozenset[PinRef], weight)]
        self._route_edges = []        # list[(PinRef, PinRef, weight)] from connect()
        self._net_colors = {}         # net_id -> color for rendered jumpers
        self._ref_counters = {}       # type-name -> count, for auto-generated instance ids
        self.board_width = board_width
        self.board_height = self.row(board_height)
        self.rotate = rotate
        board_width += 1
        board_height = self.row(board_height) + 1
        # Zero the capture frame here so the base page transforms in __init__ drop out and
        # captured geometry is in board-grid (hole) units; begin_board's own translates
        # below only re-center the board, which gen_gcode() removes by bbox-normalising.
        self._cap_ctm = [transform.IDENTITY]
        self._push()
        self._translate(self.page_width/2 + at[0], self.page_height/2 + at[1])
        self._push()
        if rotate:
            self._translate(0, -board_width/2)
            self._rotate(90)
            self.vtext(-3,-len(title)/2,title)
        else:
            self._translate(-len(title)/2, -board_height/2)
            self.text(0.5,-3,title)
        self._pop()
        self.flip_x = flip_x
        if flip_x: 
            self._flip_x()
        if self.rotate: self._rotate(90)
        self._translate(-board_width/2, -board_height/2)
        self.box(0, 0, board_width, board_height)
        letters = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 10)
        for y in range(1, board_height):
            if show_strips:
                if not self.black_and_white:
                    self.grey(240)
                    self._rect(
                        0.4,y-0.4,
                        (board_width - 0.8),0.8,
                        'F'
                    )

            if self.black_and_white:
                pass
                for x in range(1, board_width):
                    self.black()
                    self._ellipse(x,y,0.02,0.02,'F')
            else:
                self.white()
                for x in range(1, board_width):
                    self.dot(x, y, 'F')

            self.grey(220)
            if self.show_coordinates:
                self.text(-1,y,letters[y-1])
                self.text(board_width+1,y,letters[y-1])

        if self.show_coordinates:
            for x in range(1, board_width):
                if flip_x and rotate:
                    self.utext(x, -1, str(x)[::-1])
                    self.vtext(x, board_height + 1, str(x)[::-1])
                else:
                    self.utext(x, -1, str(x))
                    self.vtext(x, board_height + 1, str(x))
        self.black()
        self.show_numbers = show_numbers
        self.show_traces = show_traces
        self.show_crosses = show_crosses
        if not show_crosses: self.show_traces = False
        self.show_jumpers = show_jumpers
        self.show_components = show_components
        self.show_drills = show_drills

    def end_board(self):
        self._pop()

    def _out(self, s):
        self.pdf.out(s)

    # ---- g-code/SVG path capture --------------------------------------------------
    # The transform methods (_translate/_rotate/_scale/_flip_*/_push/_pop) feed these so
    # _cap_ctm mirrors the PDF CTM; the geometry primitives feed _cap_add() so strokes are
    # recorded in the current frame. Matrices are (a,b,c,d,e,f), same order as PDF `cm`;
    # a point maps as x' = a*x + c*y + e, y' = b*x + d*y + f.

    _cap_mul = staticmethod(transform.compose)

    def _cap_op(self, m_op):
        """Apply transform matrix m_op to the top of the capture CTM stack."""
        if self._cap_ctm:
            self._cap_ctm[-1] = transform.compose(m_op, self._cap_ctm[-1])

    def _cap_pt(self, x, y):
        return transform.apply(self._cap_ctm[-1], x, y)

    def _cap_add(self, pts):
        """Record a stroked polyline (local-coord (x,y) pairs) into _cap_paths."""
        if self._cap_on and len(pts) >= 2:
            self._cap_paths.append([self._cap_pt(px, py) for px, py in pts])

    def _rect(self,x,y,w,h,f='S'):
        self._out('%.2F %.2F m %.2F %.2F l %.2F %.2F l %.2F %.2F l %.2F %.2F l %s' %
            (x,y, x+w,y, x+w,y+h, x,y+h, x,y, f))
        if self._cap_on and f == 'S':
            self._cap_add([(x,y), (x+w,y), (x+w,y+h), (x,y+h), (x,y)])

    def _line(self,x1,y1,x2,y2,f='S'):
        self._out('%.1F %.1F m %.1F %.1F l %s' % (x1,y1,x2,y2,f))
        if self._cap_on and 'F' not in f:
            self._cap_add([(x1,y1), (x2,y2)])

    def _ellipse(self,x,y,rx,ry,f='F',tl=True,tr=True,bl=True,br=True):
        ox = rx * KAPPA
        oy = ry * KAPPA
        xe = x + rx
        ye = y + ry
        self._out('%.2F %.2F m' % (x-rx,y))
        if tl: 
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (x-rx,y-oy, x-ox,y-ry, x,y-ry))
        else:
            self._out('%.2F %.2F l %.2F %.2F l' % (x,y,x,y-ry))
        if tr: 
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (x+ox,y-ry, xe,y-oy, xe,y))
        else:
            self._out('%.2F %.2F l %.2F %.2F l' % (x,y,xe,y))
        if br: 
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (xe,y+oy, x+ox,ye, x,ye))
        else:
            self._out('%.2F %.2F l %.2F %.2F l' % (x,y,x,ye))
        if bl: 
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (x-ox,ye, x-rx,y+oy, x-rx,y))
        else:
            self._out('%.2F %.2F l %.2F %.2F l' % (x,y,x-rx,y))
        self._out(f)
        if self._cap_on and f == 'S':
            n = 32
            self._cap_add([(x + rx * math.cos(2*math.pi*i/n),
                            y + ry * math.sin(2*math.pi*i/n)) for i in range(n + 1)])

    def _arc(self,x,y,rx,ry,f='S',tl=True,tr=True,bl=True,br=True):
        ox = rx * KAPPA
        oy = ry * KAPPA
        xe = x + rx
        ye = y + ry
        if tl: 
            self._out('%.2F %.2F m' % (x-rx,y))
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (x-rx,y-oy, x-ox,y-ry, x,y-ry))
            self._out(f)
        if tr: 
            self._out('%.2F %.2F m' % (x,y-ry))
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (x+ox,y-ry, xe,y-oy, xe,y))
            self._out(f)
        if br: 
            self._out('%.2F %.2F m' % (xe,y))
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (xe,y+oy, x+ox,ye, x,ye))
            self._out(f)
        if bl: 
            self._out('%.2F %.2F m' % (x,ye))
            self._out('%.2F %.2F %.2F %.2F %.2F %.2F c' % (x-ox,ye, x-rx,y+oy, x-rx,y))
            self._out(f)
        if self._cap_on and f == 'S':
            # Approximate each enabled quadrant as an arc polyline (theta ranges:
            # br 0..pi/2, bl pi/2..pi, tl pi..3pi/2, tr 3pi/2..2pi).
            for enabled, t0 in ((br, 0.0), (bl, math.pi/2), (tl, math.pi), (tr, 3*math.pi/2)):
                if enabled:
                    self._cap_add([(x + rx*math.cos(t0 + (math.pi/2)*k/8),
                                    y + ry*math.sin(t0 + (math.pi/2)*k/8)) for k in range(9)])

    def row(self, y):
        if(isinstance(y, str)):
            y = ord(y) - 64
        return y

    def box(self, x, y, w, h, f='S'):
        if not self.show_components: return
        y = self.row(y)
        self._rect(x,y,w,h,f)

    def wire(self, x, y, x2, y2):
        y = self.row(y)
        y2 = self.row(y2)
        self._line(x,y,x2,y2)

    def vtext(self, x, y, text, y_scale=1.0):
        if not self.show_components: return
        y = self.row(y)
        chars = list(text)
        if self.rotate:
            chars.reverse()
        yy = 0
        for c in chars:
            self.draw_letter(x, y + yy, c, y_scale=y_scale)
            yy += y_scale

    def utext(self, x, y, text):
        if not self.show_components: return
        y = self.row(y)
        chars = list(text)
        if not self.rotate:
            chars.reverse()
        yy = 0
        for c in chars:
            self.draw_letter(x, y - yy, c)
            yy += 1

    def text(self, x, y, text, x_scale=1.0):
        if not self.show_components: return
        y = self.row(y)
        chars = list(text)
        xx = 0
        for c in chars:
            self.draw_letter(x + xx, y, c, x_scale=x_scale)
            xx += x_scale

    def rtext(self, x, y, text, x_scale=1.0):
        if not self.show_components: return
        y = self.row(y)
        chars = reversed(list(text))
        xx = 0
        for c in chars:
            self.draw_letter(x + xx, y, c, x_scale=x_scale)
            xx -= x_scale

    def radial(self, x, y, l, upside_down=False):
        y = self.row(y)
        self.jdot(x,y)
        self.jdot(x,y+l)
        r=l/2+0.5
        if self.show_components: self._ellipse(x,y+(l/2),r,r,f='S')

    def axial(self, x, y, l=1):
        y = self.row(y)
        yy = y - 1.5 + (l/2)
        self.black()
        if self.show_components:
            self._rect(x-0.4,y-0.4,0.8,l+0.8,f='F')
        self.jdot(x, y)
        self.jdot(x, y + l)

    def _draw_cap(self, x, y, l=1, upside_down=False, emit=True):
        y = self.row(y)
        pinmap = {'1': (x, y), '2': (x, y + l)}
        if not emit:
            return pinmap
        self.jdot(x,y)
        self.jdot(x,y+l)
        if self.show_components:
            w = 0.75
            self.wire(x, y, x, y + 0.3)
            self.wire(x, y + l, x, y + 0.7)
            self.wire(x - w, y + 0.3, x + w, y + 0.3)
            self.wire(x - w, y + 0.7, x + w, y + 0.7)
            if upside_down:
                self.wire(x + w - 0.3, y + 1.2, x + w + 0.1, y + 1.2)
                self.wire(x + w - 0.1, y + 1.0, x + w - 0.1, y + 1.4)
            else:
                self.wire(x - 0.2, y - 0.2, x - 0.6, y - 0.2)
                self.wire(x - 0.4, y - 0.0, x - 0.4, y - 0.4)
        return pinmap

    def cap(self, x, y, l=1, upside_down=False, locked=True, ref=None):
        """Draw a capacitor (pins '1'/'2') and return a :class:`Component` handle."""
        ry = self.row(y)
        pinmap = self._draw_cap(x, ry, l, upside_down, emit=locked)
        return self._register(ref or "C", pinmap, (x, ry), locked,
            redraw=lambda ox, oy, flip: self._draw_cap(
                ox, oy - l if flip else oy, l, upside_down ^ flip, emit=True))

    def _draw_sip(self, x, y, l, name, upside_down=False, pins=None, flip=False, mod=1, width=1, label_scale=1.0, emit=True):
        y = self.row(y)
        pinmap = self._sip_pins(x, y, l, pins, upside_down, mod)
        if not emit:
            return pinmap
        self.box(x - (width / 2), y - 0.5, width, l)
        for yy in range(0, l, mod):
            self.dot(x, y + yy)
        if flip:
            self.vtext(
                x + (width / 2 + 0.7),
                y + (l - len(name)) * 0.5,
                name
            )
        else:
            self.vtext(
                x - (width / 2 + 0.7),
                y + (l - len(name)) * 0.5,
                name
            )
        if upside_down:
            if self.show_components: self._ellipse(x,y+l-1,0.5,0.5,'S')
            if pins != None:
                p = 0
                for yy in reversed(range(0, l)):
                    if flip:
                        self.rtext((x - 0.4 - label_scale), yy + y, pins[p], x_scale=label_scale)
                    else:
                        self.text((x + 0.4 + label_scale), yy + y, pins[p], x_scale=label_scale)
                    p += 1
        else:
            if self.show_components: self._ellipse(x,y,0.5,0.5,'S')
            if pins != None:
                p = 0
                lp = len(pins)
                for yy in range(0, l):
                    if p < lp:
                        if flip:
                            self.rtext((x - 0.4 - label_scale), yy + y, pins[p], x_scale=label_scale)
                        else:
                            self.text((x + 0.4 + label_scale), yy + y, pins[p], x_scale=label_scale)
                    p += 1
        return pinmap

    def _sip_pins(self, x, y, l, pins, upside_down, mod):
        """Name -> world (x, y) hole map for a SIP (single column at x), mirroring
        ``_draw_sip``'s label logic. Holes sit at (x, y+yy) for yy in range(0, l, mod)."""
        y = self.row(y)
        result = {}
        if pins is None:
            for i, yy in enumerate(range(0, l, mod)):
                result[str(i + 1)] = (x, y + yy)
            return result
        p = 0
        rows = reversed(range(0, l)) if upside_down else range(0, l)
        for yy in rows:
            if p < len(pins):
                result[pins[p]] = (x, y + yy)
            p += 1
        return result

    def sip(self, x, y, l, name="", upside_down=False, pins=None, flip=False, mod=1, width=1, label_scale=1.0, locked=True, ref=None):
        """Draw a SIP footprint and return a :class:`Component` handle for autorouting."""
        ry = self.row(y)
        kwargs = dict(upside_down=upside_down, pins=pins, flip=flip, mod=mod, width=width,
                      label_scale=label_scale)
        pinmap = self._draw_sip(x, ry, l, name, emit=locked, **kwargs)
        return self._register(
            ref or name or "SIP", pinmap, (x, ry), locked,
            redraw=lambda ox, oy, flip_: self._draw_sip(
                ox, oy - (l - 1) if flip_ else oy, l, name, emit=True,
                **{**kwargs, "upside_down": upside_down ^ flip_}),
        )

    def esp32minikit(self, x, y):
        """Draw an ESP32 MiniKit footprint with its top-left pin at (x, y).

        A composite footprint: it draws sub-primitives directly rather than registering
        parts, so it returns no handle and cannot be autorouted.
        """
        y = self.row(y)
        self._draw_dip(x, y, 9, 10, "ESP32", False, [
            '7', '15', '5V', 'G', '16', '17', 'SDA', 'SCL', 'RX', 'TX',
            'RST', '36', '26', 'SCK', 'MISO', 'MOSI', 'CS0', '3V3', '13', '10'
        ],
        label_offset=0.5,
        label_scale=0.8,
        skip_pins=None
        )
        self._draw_sip(x - 1, y, 10, "", False, flip=True,
                       pins=['6', '8', '2', '0', '4', '12', '32', '25', '27', 'GND'],
                       label_scale=0.8)
        self._draw_sip(x + 10, y, 10, "", True, flip=False,
                       pins=['GND', 'NC', '39', '35', '33', '34', '14', 'NC', '9', '11'],
                       label_scale=0.8)

    def rp2040(self, x, y, locked=True, ref=None):
        # Seeed studio XIAO RP2040 module -> builder returning a Component handle.
        ry = self.row(y)
        pins = ['D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'TX', 'RX', 'D8', 'D9', 'D10', '3V3', 'GND', '5V']

        def draw(ox, oy, flip):
            dx = ox - 6 if flip else ox
            dy = oy - 6 if flip else oy  # h=7 -> h-1=6
            pm = self._draw_dip(dx, dy, 6, 7, "RP2040", upside_down=flip, pins=pins, label_scale=0.6, emit=True)
            self.box(dx + 1.5, (dy + 6.3) if flip else (dy - 1.5), 3, 1.2, 'F')
            return pm

        pinmap = draw(x, ry, False) if locked else self._dip_pins(x, ry, 6, 7, pins, False, 1, [])
        return self._register(ref or "RP2040", pinmap, (x, ry), locked, redraw=draw)

    def xiao(self, x, y, upside_down=False, labels_inside=True, label_offset=0, label_scale=0.6, mod=1, skip_pins=None, locked=True, ref=None):
        # Seeed studio XIAO RP2040 module -> builder returning a Component handle.
        ry = self.row(y)
        pins = ['D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'TX', 'RX', 'D8', 'D9', 'D10', '3V3', 'GND', '5V']

        def draw(ox, oy, flip):
            ud = upside_down ^ flip
            dx = ox - 6 if flip else ox
            dy = oy - 6 if flip else oy  # h=7 -> h-1=6
            pm = self._draw_dip(dx, dy, 6, 7, "XIAO", upside_down=ud, pins=pins,
                                labels_inside=labels_inside, label_offset=label_offset,
                                label_scale=label_scale, mod=mod, skip_pins=skip_pins, emit=True)
            self.box(dx + 1.5, (dy + 6.3) if ud else (dy - 1.5), 3, 1.2, 'F')
            return pm

        pinmap = draw(x, ry, False) if locked else self._dip_pins(x, ry, 6, 7, pins, upside_down, mod, skip_pins)
        return self._register(ref or "XIAO", pinmap, (x, ry), locked, redraw=draw)

    def digispark(self, x, y,show_port=False,ground_only=False):
        y = self.row(y)
        self.box(x-0.5,y-0.5,8,7)
        self._draw_sip(x,y+1,6,name="",pins=['D','2','C','A','1','R'])
        if ground_only: self._draw_sip(x+5,y,1,name="",pins=['GND'],flip=True)
        if not ground_only:
            self._draw_sip(x+3,y,1,name="",pins=['I'],flip=True)
            self._draw_sip(x+4,y,1,name="")
            self._draw_sip(x+5,y,1,name="",pins=['+'])
        if show_port: self.box(x+5,y+1.5,3,3,'F')

    def usb_breakout(self, x, y, show_port=False):
        y = self.row(y)
        self.box(x-0.5,y-0.5,6,5)
        self._draw_sip(x,y,5,name="",pins=['G','ID','D+','D-','5V'])
        if show_port: self.box(x+3.5,y+0.5,2,3,'F')

    def white(self):
        self.pdf.set_draw_color(255)
        self.pdf.set_fill_color(255)
        self.last_color = (255,255,255)

    def black(self):
        self.pdf.set_draw_color(0)
        self.pdf.set_fill_color(0)
        self.last_color = (0,0,0)

    def grey(self,l=128):
        if self.black_and_white:
            self.black()
            self.last_color = (0,0,0)
        else:
            self.pdf.set_draw_color(l)
            self.pdf.set_fill_color(l)
            self.last_color = (l,l,l)

    def red(self):
        self.pdf.set_draw_color(255,0,0)
        self.pdf.set_fill_color(255,0,0)
        self.last_color = (255,0,0)
    
    def blue(self):
        self.pdf.set_draw_color(16, 128, 255)
        self.pdf.set_fill_color(16, 128, 255)
        self.last_color = (16, 128, 255)
    
    def green(self):
        self.pdf.set_draw_color(16, 180, 16)
        self.pdf.set_fill_color(16, 180, 16)
        self.last_color = (16, 180, 16)

    def color(self,r,g=0,b=0):
        if isinstance(r, tuple):
            g = r[1]
            b = r[2]
            r = r[0]
        self.pdf.set_draw_color(r,g,b)
        self.pdf.set_fill_color(r,g,b)
        self.last_color = (r,g,b)

    def power(self, x, y,upside_down=False):
        y = self.row(y)
        if upside_down:
            self.box(x-2,y-0.5,3.5,5)
            self.text(x+1,y+2,'-')
            self.drill(x,y+2)
            self.drill(x-2,y+1)
            self.drill(x,y)
            self.text(x+1,y,'+')
            self.text(x-1,y+1,'S')
        else:
            self.box(x-2,y-4.5,3.5,5)
            self.text(x+1,y-2,'-')
            self.drill(x,y-2)
            self.drill(x-2,y-1)
            self.drill(x,y)
            self.text(x+1,y,'+')
            self.text(x-1,y-1,'S')

    def shroud(self,x,y,l=8):
        y = self.row(y)
        self.box(x-1,y-2,3,l+3,'F')
        self.header(x,y,l)
        self.header(x+1,y,l)
        self.white()
        self.box(x+1.7,y-2+(l+1)/2,0.35,2,'F')
        self.black()

    def _draw_dip(self, x, y, w, h, name="", upside_down=False, pins=None, labels_inside=True, label_offset=0, label_scale=0.78, mod=1, skip_pins=None, emit=True):
        y = self.row(y)
        skip_pins = () if skip_pins is None else skip_pins
        pinmap = self._dip_pins(x, y, w, h, pins, upside_down, mod, skip_pins)
        if not emit:
            return pinmap

        self.box(x + 0.5, y - 0.5, w - 1, h)
        for yy in range(0, h, mod):
            skipPin = yy+1 in skip_pins
            if not skipPin:
                if self.show_components: self.wire(x, y + yy, x + 0.5, y + yy)
                self.dot(x, y + yy)
        for yy in range(h-1, -1, -mod):
            if not h*2-yy in skip_pins:
                if self.show_components: self.wire(x + w, y + yy, x + w - 0.5, y + yy)
                self.dot(x + w, y + yy)


        if upside_down:
            if self.show_components: self._ellipse(x + w, y + h - 1, 0.5, 0.5, 'S')
            if pins != None:
                p = 0
                for yy in reversed(range(0, h, mod)):
                    if labels_inside:
                        self.rtext((x + w - label_scale - 0.3), yy + y, pins[p], x_scale=label_scale)
                    else:
                        self.text((x + w + label_scale + 0.3), yy + y, pins[p], x_scale=label_scale)
                    p += 1
                for yy in range(0, h, mod):
                    if labels_inside:
                        self.text((x + label_scale + 0.3), yy + y, pins[p], x_scale=label_scale)
                    else:
                        self.rtext((x - label_scale - 0.3), yy + y, pins[p], x_scale=label_scale)
                    p += 1
        else:
            if self.show_components: self._ellipse(x,y,0.5,0.5,'S')
            if pins != None:
                p = 0
                lp = len(pins)
                for yy in range(0, h, mod):
                    if p < lp:
                        if labels_inside:
                            self.text((x + label_scale + 0.3), yy + y, pins[p], x_scale=label_scale)
                        else:
                            self.rtext((x - label_scale - 0.1), yy + y, pins[p], x_scale=label_scale)
                    p += 1
                for yy in reversed(range(0, h, mod)):
                    if p < lp:
                        if labels_inside:
                            self.rtext((x + w - label_scale - 0.3), yy + y, pins[p], x_scale=label_scale)
                        else:
                            self.text((x + w + label_scale + 0.1), yy + y, pins[p], x_scale=label_scale)
                    p += 1

        if self.black_and_white:
            if name != '':
                self.black()
                xx = x + math.floor(w / 2) + label_offset
                self.box(xx - 0.5, y - 0.5, 1, h, f='F')
                self.white()
                self.vtext(xx, y + (h - len(name)) * 0.5, name)
                self.black()
        else:
            self.pdf.set_draw_color(255)
            self.pdf.set_fill_color(128)
            self.pdf.set_alpha(1.0)
            if name != '':
                xx = x + math.floor(w / 2) + label_offset
                self.box(xx - 0.5, y - 0.5, 1, h, f='F')
                self.pdf.set_alpha(1)
                self.vtext(xx, y + (h - len(name)) * 0.5, name)
            self.pdf.set_alpha(1)
            self.pdf.set_draw_color(0)
            self.pdf.set_fill_color(0)
        return pinmap

    def _dip_pins(self, x, y, w, h, pins, upside_down, mod, skip_pins=None):
        """Name -> world (x, y) hole map for a DIP, mirroring ``_draw_dip``'s label logic.

        Left column at x (physical pins 1..h, top->bottom), right column at x+w (pins
        h+1..2h, bottom->top). ``upside_down`` rotates the ``pins`` labeling 180 degrees;
        ``skip_pins`` (physical pin numbers) drops missing holes. Holes are a function of
        (x, row(y), w, h, mod, skip_pins) only -- upside_down never moves a hole.
        """
        skip_pins = () if skip_pins is None else skip_pins
        y = self.row(y)
        result = {}
        if pins is None:
            for yy in range(0, h, mod):
                if yy + 1 not in skip_pins:
                    result[str(yy + 1)] = (x, y + yy)
            for yy in range(h - 1, -1, -mod):
                if h * 2 - yy not in skip_pins:
                    result[str(h * 2 - yy)] = (x + w, y + yy)
            return result
        p = 0
        if upside_down:
            for yy in reversed(range(0, h, mod)):   # right column, bottom->top
                if p < len(pins) and h * 2 - yy not in skip_pins:
                    result[pins[p]] = (x + w, y + yy)
                p += 1
            for yy in range(0, h, mod):              # left column, top->bottom
                if p < len(pins) and yy + 1 not in skip_pins:
                    result[pins[p]] = (x, y + yy)
                p += 1
        else:
            for yy in range(0, h, mod):              # left column, top->bottom
                if p < len(pins) and yy + 1 not in skip_pins:
                    result[pins[p]] = (x, y + yy)
                p += 1
            for yy in reversed(range(0, h, mod)):    # right column, bottom->top
                if p < len(pins) and h * 2 - yy not in skip_pins:
                    result[pins[p]] = (x + w, y + yy)
                p += 1
        return result

    def dip(self, x, y, w, h, name="", upside_down=False, pins=None, labels_inside=True, label_offset=0, label_scale=0.78, mod=1, skip_pins=None, locked=True, ref=None):
        """Draw a DIP footprint and return a :class:`Component` handle for autorouting."""
        ry = self.row(y)
        kwargs = dict(name=name, upside_down=upside_down, pins=pins, labels_inside=labels_inside,
                      label_offset=label_offset, label_scale=label_scale, mod=mod, skip_pins=skip_pins)
        pinmap = self._draw_dip(x, ry, w, h, emit=locked, **kwargs)
        # Flip mapping: the router's 180-degree flip is (dx,dy)->(-dx,-dy). For the
        # rectangular DIP grid that equals drawing unflipped at (ox-w, oy-(h-1)) with the
        # label orientation toggled -- verified to land on the solver's world pins exactly.
        return self._register(
            ref or name or "DIP", pinmap, (x, ry), locked,
            redraw=lambda ox, oy, flip: self._draw_dip(
                ox - w if flip else ox, oy - (h - 1) if flip else oy, w, h, emit=True,
                **{**kwargs, "upside_down": upside_down ^ flip}),
        )

    def off_right(self, x, y, text):
        if not self.show_components: return
        y = self.row(y)
        x2 = self.board_width+1

        self.dot(x, y)
        self.blue()
        self.wire(x,y,x2,y)
        self.polyline([
            x2,y,
            x2+0.5,y-0.5,
            x2+0.7+len(text),y-0.5,
            x2+0.7+len(text),y+0.5,
            x2+0.5,y+0.5,
            x2,y
        ],'F')
        self.white()
        self.text(x2+1,y,text)
        self.black()


    def pot(self, x, y, upside_down=False):
        y = self.row(y)
        self.dot(x, y + 0)
        self.dot(x, y + 1)
        self.dot(x, y + 2)
        if not self.show_components: return
        if upside_down:
            self.box(x - 5, y - 1, 4, 4)
            self.wire(x, y, x - 1, y)
            self.wire(x, y + 1, x - 1, y + 1)
            self.wire(x, y + 2, x - 1, y + 2)

            self.cut(x - 3, y - 1)
            self.cut(x - 3, y + 3)
            self._ellipse(x - 3,y + 1,1,1,'F')
            self.pdf.set_draw_color(255)
            self.wire(x - 3, y + 1, x - 4, y + 1)
            self.pdf.set_draw_color(0)
            self._ellipse(x - 3, y + 1, 1.3, 1.3, 'S')
        else:
            self.box(x + 1, y - 1, 4, 4)
            self.wire(x, y, x + 1, y)
            self.wire(x, y + 1, x + 1, y + 1)
            self.wire(x, y + 2, x + 1, y + 2)
            self.cut(x + 3, y - 1)
            self.cut(x + 3, y + 3)
            self._ellipse(x + 3,y + 1,1,1,'F')
            self.pdf.set_draw_color(255)
            self.wire(x + 3, y + 1, x + 4, y + 1)
            self.pdf.set_draw_color(0)
            self._ellipse(x + 3, y + 1, 1.3, 1.3, 'S')

    def jack(self, x, y, upside_down=False):
        y = self.row(y)
        if upside_down:
            if self.show_components:
                self._rect(x-1.5,y-0.5,3,4,'F')
                self.text(x+1,y+4,'R')
                self.white()
                self.text(x+1,y+3,'S')
                self.text(x+1,y,'T')
                self._ellipse(x,y+1.5,1,1)
                self.black()
                self._ellipse(x,y+1.5,0.75,0.75)
            self.jdot(x, y)
            self.jdot(x, y + 3)
            self.jdot(x, y + 4)
        else:
            if self.show_components:
                self._rect(x-1.5,y+0.5,3,4,'F')
                self.text(x+1,y,'R')
                self.white()
                self.text(x+1,y+1,'S')
                self.text(x+1,y+4,'T')
                self._ellipse(x,y+2.5,1,1)
                self.black()
                self._ellipse(x,y+2.5,0.75,0.75)
            self.jdot(x, y)
            self.jdot(x, y + 1)
            self.jdot(x, y + 4)

    def header(self, x, y, h):
        y = self.row(y)
        if self.show_components:
            self._rect(
                x-0.5,
                y-0.6,
                (1),
                (h + 0.2),
                'F'
            )
            self.white()
            for yy in range(y, y + h):
                self.dot(x, yy, 'F')
            self.black()
        elif self.show_crosses:
            self.black()
            for yy in range(y, y + h):
                self.dot(x, yy, 'F')

    def hheader(self, x, y, w):
        y = self.row(y)
        if self.show_components:
            self._rect(
                x-0.5,
                y-0.4,
                ((w+1) * 0.8),
                (0.8),
                'F'
            )
            self.white()
            for xx in range(x, x + w):
                self.dot(xx, y, 'F')
            self.black()
            for xx in range(x, x + w - 1):
                self.cut(xx+0.5,y)
        elif self.show_crosses:
            self.black()
            for xx in range(x, x + w):
                self.dot(xx, y, 'F')
            for xx in range(x, x + w - 1):
                self.cut(xx+0.5,y)

    def hres(self, x, y, val,l=4):
        y = self.row(y)
        if self.show_components:
            self.dot(x, y)
            self.wire(x, y, x + 0.4, y)
            self.box(x + 0.4, y - 0.5, l + 0.2, 1, 'F')
        self.cut(x + 1, y)
        if self.show_components:
            self.wire(x + l +0.6, y, x + l + 1, y)
            self.dot(x + l + 1, y)
            self.white()
            self.text(x + 1, y, val)
            self.black()

    def _draw_big_button(self, x, y, emit=True):
        y = self.row(y)
        pinmap = {'AL': (x, y), 'BL': (x, y + 2), 'AR': (x + 5, y), 'BR': (x + 5, y + 2)}
        if not emit:
            return pinmap
        self.dot(x, y)
        if self.show_components: self.wire(x, y, x + 0.5, y)
        self.dot(x, y + 2)
        if self.show_components: self.wire(x, y + 2, x + 0.5, y + 2)
        self.dot(x + 5, y)
        if self.show_components: self.wire(x + 5, y, x + 5 - 0.5, y)
        self.dot(x + 5, y + 2)
        if self.show_components: self.wire(x + 5, y + 2, x + 5 - 0.5, y + 2)
        if self.show_components: self.box(x + 0.5, y - 1, 4, 4)
        if self.show_components: self._ellipse(x + 2.5, y + 1, 1.5, 1.5)
        return pinmap

    def big_button(self, x, y, locked=True, ref=None):
        """Draw a 4-leg tactile switch and return a :class:`Component` handle.

        The four legs are independent pins: top row AL, AR; bottom row BL, BR. Each
        terminal's two legs sit on the *same* board row, so the row's copper strip ties
        them -- declare both legs of a terminal in the same net and the router lays that
        strip. (Modelling them as length-0 internal ties instead lets cut-minimization
        sever the strip between them, so we don't.) The solid body between the legs is a
        keep-out so jumpers can't arc under it (local rect from the hand layout)."""
        ry = self.row(y)
        pinmap = self._draw_big_button(x, ry, emit=locked)
        return self._register(
            ref or "BTN", pinmap, (x, ry), locked,
            keepouts=((1, -1, 4, 3),),
            redraw=lambda ox, oy, flip: self._draw_big_button(
                ox - 5 if flip else ox, oy - 2 if flip else oy, emit=True))

    def button(self, x, y):
        y = self.row(y)
        self.dot(x,y)
        if self.show_components: self.wire(x,y,x+0.5,y)
        self.dot(x+3,y)
        if self.show_components: self.wire(x+3,y,x+2.5,y)
        self.dot(x,y+2)
        if self.show_components: self.wire(x,y+2,x+0.5,y+2)
        self.dot(x+3,y+2)
        if self.show_components: self.wire(x+3,y+2,x+2.5,y+2)
        if self.show_components: self.box(x+0.5,y,2,2)
        if self.show_components: self._ellipse(x+1.5,y+1,0.75,0.75)

    def _draw_led(self, x, y, upside_down=False, len=1, weight=0.5, emit=True):
        y = self.row(y)
        pinmap = {'A': (x, y), 'K': (x, y + len)}
        if not emit:
            return pinmap
        if self.show_components or self.show_crosses:
            self.dot(x, y)
            self.dot(x, y + len)
        if self.show_components:
            yy = y + ((len-1)*weight)
            self.wire(x,y,x,yy)
            self.wire(x,yy+1.0,x,y+len)

            self._ellipse(x, yy+0.5, 0.75, 0.75, 'S')
            if upside_down:
                self.wire(x - 0.5, yy + 0.8, x + 0.5, yy + 0.8)
                self.wire(x - 0.5, yy + 0.8, x, yy + 0.2)
                self.wire(x + 0.5, yy + 0.8, x, yy + 0.2)
                self.wire(x - 0.5, yy + 0.2, x + 0.5, yy + 0.2)
            else:
                self.wire(x - 0.5, yy + 0.2, x + 0.5, yy + 0.2)
                self.wire(x - 0.5, yy + 0.2, x, yy + 0.8)
                self.wire(x + 0.5, yy + 0.2, x, yy + 0.8)
                self.wire(x - 0.5, yy + 0.8, x + 0.5, yy + 0.8)
        return pinmap

    def led(self, x, y, upside_down=False, len=1, weight=0.5, locked=True, ref=None):
        """Draw an LED (pins 'A'=anode / 'K'=cathode) and return a :class:`Component`."""
        ry = self.row(y)
        pinmap = self._draw_led(x, ry, upside_down, len, weight, emit=locked)
        return self._register(ref or "LED", pinmap, (x, ry), locked,
            redraw=lambda ox, oy, flip: self._draw_led(
                ox, oy - len if flip else oy, upside_down ^ flip, len, weight, emit=True))

    def _draw_diode(self, x, y, upside_down=False, len=1, emit=True):
        y = self.row(y)
        pinmap = {'A': (x, y), 'K': (x, y + len)}
        if not emit or not self.show_components:
            return pinmap
        self.dot(x, y)
        self.dot(x, y + len)
        yy = y - 0.5 + (len/2)
        self.wire(x,y,x,yy)
        self.wire(x,yy+1.0,x,y+len)

        self.wire(x - 0.5, yy + 0.2, x + 0.5, yy + 0.2)
        self.wire(x - 0.5, yy + 0.2, x, yy + 0.8)
        self.wire(x + 0.5, yy + 0.2, x, yy + 0.8)
        self.wire(x - 0.5, yy + 0.8, x + 0.5, yy + 0.8)
        return pinmap

    def diode(self, x, y, upside_down=False, len=1, locked=True, ref=None):
        """Draw a diode (pins 'A'=anode / 'K'=cathode) and return a :class:`Component`."""
        ry = self.row(y)
        pinmap = self._draw_diode(x, ry, upside_down, len, emit=locked)
        return self._register(ref or "D", pinmap, (x, ry), locked,
            redraw=lambda ox, oy, flip: self._draw_diode(
                ox, oy - len if flip else oy, upside_down ^ flip, len, emit=True))

    def zener(self, x, y, upside_down=False, len=1):
        if not self.show_components: return
        y = self.row(y)
        self.dot(x, y)
        self.dot(x, y + len)
        yy = y - 0.5 + (len/2)
        self.wire(x,y,x,yy)
        self.wire(x,yy+1.0,x,y+len)
        if upside_down:
            self.wire(x - 0.5, yy + 0.8, x + 0.5, yy + 0.8 )
            self.wire(x - 0.5, yy + 0.8, x      , yy + 0.2 )
            self.wire(x + 0.5, yy + 0.8, x      , yy + 0.2 )
            self.wire(x - 0.5, yy + 0.2, x + 0.5, yy + 0.2 )
            self.wire(x - 0.5, yy + 0.2, x - 0.5, yy + 0.0 )
            self.wire(x + 0.5, yy + 0.2, x + 0.5, yy + 0.4 )
        else:
            self.wire(x - 0.5, yy + 0.2, x + 0.5, yy + 0.2 )
            self.wire(x - 0.5, yy + 0.2, x      , yy + 0.8 )
            self.wire(x + 0.5, yy + 0.2, x      , yy + 0.8 )
            self.wire(x - 0.5, yy + 0.8, x + 0.5, yy + 0.8 )
            self.wire(x - 0.5, yy + 0.8, x - 0.5, yy + 0.6 )
            self.wire(x + 0.5, yy + 0.8, x + 0.5, yy + 1.0 )

    def _draw_resist(self, x, y, val='', upside_down=False, l=1, label_scale=1.0, emit=True):
        y = self.row(y)
        pinmap = {'2': (x, y), '1': (x, y + l)} if upside_down else {'1': (x, y), '2': (x, y + l)}
        if not emit:
            return pinmap
        yy = y - 1.5 + (l/2)
        self.black()
        if l <= 2:
            if self.show_components:
                self._rect(x-0.4,y-0.4,0.8,l+0.8,f='F')
            self.jdot(x, y)
            self.jdot(x, y + l)
        else:
            if self.show_components: 
                self._rect(x-0.5,yy,1,3,f='F')
            self.jdot(x, y)
            self.jdot(x, y + l)
            if self.show_components: 
                self.wire(x,y,x,yy)
                self.wire(x,yy+3.0,x,y+l)
        if self.show_components:
            self.white()
            if l >= len(val):
                # Center the stacked label on the resistor rect (center at yy+1.5).
                self.vtext(x, yy + 1.5 - (len(val) - 1) * label_scale / 2, val, y_scale=label_scale)
        self.black()
        return pinmap

    def resist(self, x, y, val='', upside_down=False, l=1, label_scale=1.0, locked=True, ref=None):
        """Draw a resistor (pins '1'/'2') and return a :class:`Component` handle.

        The body occupies the column between the two pins, so the interior cells are a
        keep-out -- other jumpers may not arc through the resistor (local rect, empty when
        the pins are adjacent). ``label_scale`` vertically scales the value label (< 1
        shortens it to fit a busy board, > 1 stretches it taller)."""
        ry = self.row(y)
        pinmap = self._draw_resist(x, ry, val, upside_down, l, label_scale=label_scale, emit=locked)
        keepouts = ((0, 1, 0, l - 1),) if l >= 2 else ()
        return self._register(ref or "R", pinmap, (x, ry), locked, keepouts=keepouts,
            redraw=lambda ox, oy, flip: self._draw_resist(
                ox, oy - l if flip else oy, val, upside_down ^ flip, l, label_scale=label_scale, emit=True))

    def keepout(self, x, y, w=1, h=1, show=False, ref=None):
        """Register a pin-less keep-out region and return the :class:`Component` handle.

        Covers the ``w`` x ``h`` block of board cells whose top-left cell is ``(x, y)``
        (``y`` accepts a row letter). It has no pins and draws no component -- it is purely
        a routing constraint: the autorouter forbids pins and jumper arcs on those cells,
        so use it to reserve space under a mounting hole, a tall part, or any mechanical
        obstruction. The region is always locked (fixed where you place it). With ``show``
        (default) it is shaded in the current view so you can see it while designing; pass
        ``show=False`` for an invisible constraint."""
        ry = self.row(y)
        if show:
            self._shade_rect(x - 0.5, ry - 0.5, w, h)
        return self._register(ref or "KO", {}, (x, ry), locked=True,
                              keepouts=((0, 0, w - 1, h - 1),))

    def part2pin(self, x, y, val='', upside_down=False, l=1):
        y = self.row(y)
        if self.show_components:
            yy = y
            self.black()
            self._rect(x-0.4,yy,0.8,l,f='F')
            self.jdot(x, y)
            self.jdot(x, y + l)
            self.white()
            self.vtext(x,yy+2-(len(val)/2),val)
            self.black()
        elif self.show_crosses:
            self.jdot(x, y)
            self.jdot(x, y + l)

    def t3904(self, x, y, upside_down=False):
        if not self.show_components: return
        y = self.row(y)
        self.grey(160)
        if upside_down:
            self._ellipse(x-0.2,y,1.2,1.2,'F',tl=False,bl=False)
        else:
            self._ellipse(x-0.2,y,1.2,1.2,'F',tr=False,br=False)
        self.black()
        if upside_down:
            self.text(x+1, y-1, 'E')
        else:
            self.text(x+1, y-1, 'C')
        self.jdot(x, y-1)
        self.text(x-1, y, 'B')
        self.jdot(x, y)
        if upside_down:
            self.text(x+1, y+1, 'C')
        else:
            self.text(x+1, y+1, 'E')
        self.jdot(x, y+1)

    def dot(self, x, y, f='F'):
        y = self.row(y)
        if self.show_components:
            self._ellipse(x,y,0.25,0.25,f)
        elif self.show_crosses:
            self._ellipse(x,y,0.1,0.1,f)

    def jdot(self, x, y, f='F'):
        y = self.row(y)
        if self.show_jumpers:
            self.white()
            self._ellipse(x,y,0.35,0.35,f)
            self.black()
            self._ellipse(x,y,0.25,0.25,f)
        elif self.show_crosses:
            self.black()
            self._ellipse(x,y,0.1,0.1,f)   
        else:
            self.white()
            self._ellipse(x,y,0.2,0.2,f)   
            self.black()
            self._ellipse(x,y,0.15,0.15,f)   

    def drill(self, x, y):
        if not self.show_drills: return
        y = self.row(y)
        self._ellipse(x,y,0.25,0.25,'F')
        self._ellipse(x,y,0.5,0.5,'S')

    def cut(self, x, y, y2=None):
        if not self.show_crosses: return
        y = self.row(y)
        if y2 == None:
            y2 = y
        y2 = self.row(y2)
        xx = x
        self.pdf.set_draw_color(255, 0, 0)
        r = 0.3
        for yy in range(int(y), int(y2) + 1):
            self.connections.append((False, x, yy))
            yyy = yy
            if x != math.floor(x):
                self._line(
                    (xx),
                    (yyy - 0.5),
                    (xx),
                    (yyy + 0.5)
                )
            else:
                self._line(
                    (xx - r),
                    (yyy - r),
                    (xx + r),
                    (yyy + r)
                )
                self._line(
                    (xx - r),
                    (yyy + r),
                    (xx + r),
                    (yyy - r)
                )
        self.pdf.set_draw_color(0)

    def nc(self, x, y):
        if not self.show_traces: return
        y = self.row(y)
        self.nc_points.append((x, y))
        self.pdf.set_draw_color(136, 136, 136)   # #888
        self.line_width(0.2)
        self._line(x - 0.3, y - 0.3, x + 0.3, y + 0.3)
        self._line(x - 0.3, y + 0.3, x + 0.3, y - 0.3)
        self.pdf.set_draw_color(0)

    def draw_cuts(self):
        self.pdf.set_draw_color(255, 0, 0)
        r = 0.3
        for con in self.connections:
            if not con[0]:  # Cut
                xx = con[1]
                yyy = con[2]
                if xx != math.floor(xx):
                    # Cut
                    self._line(
                        (xx),
                        (yyy - 0.5),
                        (xx),
                        (yyy + 0.5)
                    )
                else:
                    # Cross
                    self._line(
                        (xx - r),
                        (yyy - r),
                        (xx + r),
                        (yyy + r)
                    )
                    self._line(
                        (xx - r),
                        (yyy + r),
                        (xx + r),
                        (yyy - r)
                    )
        self.pdf.set_draw_color(0)

    def jumper(self, x, y, x2, y2, color='blue', show_length=True):
        if isinstance(color, str):
            color = self.wire_colors[color]
        y = self.row(y)
        y2 = self.row(y2)
        if self.show_jumpers:
            self._check_jumper_hole(x, y)
            self._check_jumper_hole(x2, y2)
            self.connections.append((True, x, y, x2, y2))
            self.connections.append((True, x2, y2, x, y))
        self.jdot(x, y)
        self.jdot(x2, y2)
        if self.show_jumpers:
            if self.black_and_white:
                self.black()
                self.line_width(.05)
            else:
                self.pdf.set_draw_color(*color)
            self.wire(x, y, x2, y2)

            dist = int(((x2 - x)**2 + (y2 - y)**2)**0.5)
            if dist > 1 and self.show_numbers and show_length:
                dist = str(dist)
                self.pdf.set_fill_color(255)
                self._rect(
                    (x-0.5) + (x2 - x) / 2,
                    (y-0.5) + (y2 - y) / 2,
                    1,
                    len(dist),
                    "F"
                )
                if self.black_and_white:
                    self.black()
                else:
                    self.pdf.set_draw_color(*color)
                self.vtext(x + (x2 - x) / 2, y + (y2 - y) / 2, dist)
            if self.black_and_white:
                self.line_width(.2)

        self.pdf.set_draw_color(0)
        self.pdf.set_fill_color(0)

    def row_name(self, y):
        y = self.row(y)
        if 1 <= y <= 26:
            return chr(64 + y)
        return str(y)

    def _check_jumper_hole(self, x, y):
        # A stripboard hole only takes one wire end; warn if a second jumper
        # lands in a hole already occupied by another jumper.
        for con in self.connections:
            if con[0] and con[1] == x and con[2] == y:
                _warn("Jumper conflict! Two jumpers in the same hole "
                      f"x={x} y={self.row_name(y)}", JumperConflictWarning)
                return

    def _draw_terminal(self, x, y, h, mod=1, shroud_y_offset=0, emit=True):
        y = self.row(y)
        pinmap = {str(i + 1): (x, yy) for i, yy in enumerate(range(y, y + h, mod))}
        if not emit:
            return pinmap
        if self.show_components:
            self._rect(
                x-1,
                y-0.4+shroud_y_offset,
                (2.5),
                (h - 0.2),
                'F'
            )
            self.white()
            for yy in range(y, y + h, mod):
                self.dot(x, yy, 'F')
            self.black()
        elif self.show_crosses:
            self.black()
            for yy in range(y, y + h):
                self.dot(x, yy, 'F')
        return pinmap

    def _terminal_keepouts(self, x, y, h, shroud_y_offset):
        """Local keep-out rects for a terminal block's shroud (empty if it covers no hole).

        The shroud is drawn from ``(x-1, y-0.4+shroud_y_offset)`` spanning ``2.5 x (h-0.2)``,
        so it buries every hole whose center falls inside that rect -- columns x-1..x+1 and
        the rows the plastic reaches (``shroud_y_offset`` shifts those, e.g. a mod=2 block
        centered on its pin pairs covers one row less). Clamped to the board, since a
        connector normally overhangs an edge and an off-board keep-out is an error."""
        x0 = max(x - 1, 1) - x
        x1 = min(x + 1, self.board_width) - x
        y0 = max(y + math.ceil(shroud_y_offset - 0.4), 1) - y
        y1 = min(y + math.floor(h - 0.6 + shroud_y_offset), self.board_height) - y
        return ((x0, y0, x1, y1),) if x0 <= x1 and y0 <= y1 else ()

    def terminal(self, x, y, h, mod=1, shroud_y_offset=0, ref=None):
        """Draw a screw-terminal block (pins '1', '2', ... top to bottom) and return a
        :class:`Component` handle.

        The plastic shroud sits on top of the holes around the legs, so the body is a
        keep-out like the resistor's: copper strips still run under it, but no other part's
        pin and no jumper end or arc may land beneath the plastic. ``h`` is the shroud height
        in holes and ``mod`` the leg pitch, so a 6-way 0.2"-pitch block is ``h=12, mod=2``.
        The block is always locked -- a connector's position is a mechanical constraint, not
        something for the placer to optimize."""
        ry = self.row(y)
        pinmap = self._draw_terminal(x, ry, h, mod, shroud_y_offset)
        return self._register(ref or "TERM", pinmap, (x, ry), locked=True,
                              keepouts=self._terminal_keepouts(x, ry, h, shroud_y_offset))

    def bus(self, x, y1, y2):
        """Chain single-row jumpers down column `x` from row `y1` to `y2`.

        This is a single bare wire run down the column and soldered where it crosses
        each strip, so it ties every strip in the span into one net. Drawn as one wire
        rather than a ladder of separate jumpers, because a stripboard hole only takes
        one wire end.
        """
        y1, y2 = self.row(y1), self.row(y2)
        if y2 < y1:
            y1, y2 = y2, y1
        for i in range(y1, y2):
            self.connections.append((True, x, i, x, i + 1))
            self.connections.append((True, x, i + 1, x, i))
        for i in range(y1, y2 + 1):
            self.jdot(x, i)
        if self.show_jumpers:
            if self.black_and_white:
                self.black()
                self.line_width(.05)
            else:
                self.pdf.set_draw_color(*self.wire_colors['blue'])
            self.wire(x, y1, x, y2)
            if self.black_and_white:
                self.line_width(.2)
        self.pdf.set_draw_color(0)
        self.pdf.set_fill_color(0)

    def trace_jumper(self, x, y, x2, y2, color):
        if not self.show_jumpers: return
        y = self.row(y)
        if(isinstance(y2, str)):
            y2 = ord(y2) - 64
        self.jdot(x, y)
        self.jdot(x2, y2)
        self.pdf.set_draw_color(*color)
        self.wire(x, y, x2, y2)

        dist = int(((x2 - x)**2 + (y2 - y)**2)**0.5)
        if dist > 1 and self.show_numbers:
            dist = str(dist)
            self.pdf.set_fill_color(255)
            self._rect(
                (x + (x2 - x) / 2)-0.5,
                (y + (y2 - y) / 2)-0.5,
                1,
                len(dist),
                "F"
            )
            self.pdf.set_draw_color(*color)
            self.vtext(x + (x2 - x) / 2, y + (y2 - y) / 2, dist)

        self.pdf.set_draw_color(*color)
        self.pdf.set_fill_color(0)

    def trace(self, x, y, color=None):
        if not self.show_traces: return
        y = self.row(y)
        marked = []
        if color == None:
            color = self.colors[self.trace_color]
        self.trace_point(x, y, marked, color, first=True)
        self.pdf.set_draw_color(0)
        self.pdf.set_fill_color(0)
        self.trace_color = (self.trace_color + 1) % len(self.colors)

    def trace_point(self, x, y, marked, color, first=False):
        for mark in marked:
            if mark[0] == x and mark[1] == y:
                return
        marked.append((x, y))
        for ncx, ncy in self.nc_points:
            if ncx == x and ncy == y:
                _warn("Short circuit! Trace reached a not-connected point "
                      f"x={x} y={self.row_name(y)}", ShortCircuitWarning)
                break
        foundLeftSlice = False
        foundRightSlice = False
        for con in self.connections:
            if con[1] == x and con[2] == y:
                if con[0]:  # Jumper
                    self.trace_jumper(con[1], con[2], con[3], con[4], color)
                    self.trace_point(con[3], con[4], marked, color)
                else:  # Cross
                    return
            if con[1] == x + 0.5 and con[2] == y:
                foundRightSlice = True
            if con[1] == x - 0.5 and con[2] == y:
                foundLeftSlice = True
        for origin in self.trace_origins:
            if origin[0] == x and origin[1] == y:
                _warn(f"Trace collision! Two traced nets meet at "
                      f"x={x} y={self.row_name(y)}", TraceCollisionWarning)
                break
        if first:
            self.trace_origins.append((x,y))
        if x > 1 and not foundLeftSlice:
            self.trace_point(x - 1, y, marked, color)
        if x < self.board_width+10 and not foundRightSlice:
            self.trace_point(x + 1, y, marked, color)
        if x <= self.board_width:
            self.pdf.set_draw_color(*color)
            self.pdf.set_fill_color(*color)
            if first:
                self.pdf.set_alpha(0.7)
                #self._ellipse(x,y,0.5,0.5)
                self.pdf.set_alpha(1.0)
                #self.white()
                self._rect(x-0.45,y-0.45,0.9,0.9,'S')
            else:
                self.pdf.set_alpha(0.45)
                self._rect(x-0.5,y-0.5,1,1,'F')

            self.pdf.set_alpha(1.0)

    def polyline(self, poly, f='S'):
        pdf = self.pdf
        for i in range(0, len(poly), 2):
            op = 'm' if i == 0 else 'l'
            pdf.out('%.2f %.2f %s ' % (poly[i + 0], poly[i + 1], op))
        pdf.out(f)
        if self._cap_on and f == 'S':
            self._cap_add([(poly[i], poly[i + 1]) for i in range(0, len(poly) - 1, 2)])

    def copyright(self,x,y):
        if not self.show_components: return
        y = self.row(y)
        self.line_width(0.15)
        self._push()
        self._translate(x,y)
        self._ellipse(0,0,0.4,0.4,'S')
        self._rotate(45)
        self._arc(0,0,0.18,0.18,tl=False)
        self._pop()
        self.line_width(0.2)


    def draw_letter(self, x, y, c, x_scale=1.0, y_scale=1.0):
        xs = 0.8 / 5
        ys = 0.8 / 5
        y = self.row(y)
        xx = x - 0.31
        yy = y - 0.31

        self.line_width(0.15)
        v = self.vector_chars.get(c)
        if v is None:
            # A stray character in a label should not abort the whole render.
            _warn(f"No glyph for {c!r} in the built-in stroke font; skipping it.",
                  MissingGlyphWarning)
            return
        self._push()
        self._translate(x,y)
        self._scale(x_scale,y_scale)
        if self.rotate:
            self._rotate(-90)
        if self.flip_x:
            self._flip_x()
        last_color = self.last_color
        if self.black_and_white:
            if self.last_color == (255,255,255):
                self.black()
            else:
                self.white()
            self.box(-0.5,-0.5,1.0,1.0,'F')
            self.color(last_color)
        for poly in v:
            line = []
            for i in range(0, len(poly), 2):
                line.append(poly[i + 0] * xs - 0.31)
                line.append(poly[i + 1] * ys - 0.31)
            self.polyline(line)
        self._pop()
        self.line_width(0.2)

    # ---------------------------------------------------------------- autoroute API
    #
    # The part builders (xiao/dip/sip/led/resist/cap/big_button/...) register a Component
    # each time the board's draw lambda runs. net()/connect() declare the electrical
    # intent. autoroute() builds a router problem from those, solves it ONCE (cached
    # by a signature, so a board drawn in FRONT/BACK/DESIGN views is solved a single time),
    # and draws the resulting jumpers + cuts (and any auto-placed parts) into the current
    # view. jumper()/cut() already honor the per-view show flags, so cuts appear only where
    # show_crosses and jumpers only where show_jumpers -- no per-view branching needed here.

    def _register(self, base, pinmap, origin, locked, keepouts=(), internal=(), redraw=None):
        """Record a built Component (auto-numbering its id) and return the handle."""
        n = self._ref_counters.get(base, 0) + 1
        self._ref_counters[base] = n
        cid = base if n == 1 else f"{base}{n}"
        comp = Component(cid, pinmap, origin, locked, keepouts, internal, redraw)
        self._route_components.append(comp)
        return comp

    def _ensure_router(self):
        """Return the autorouter module (:mod:`stripboard.router`).

        The router ships inside this package, so this is just an accessor now -- it
        survives as a method because the netlist/autoroute code and the tests reach for
        the router through it.
        """
        if self._router is None:
            from . import router
            self._router = router
        return self._router

    def _as_ref(self, p):
        """Coerce a pin argument to a (instance_id, local_id) reference."""
        if (isinstance(p, tuple) and len(p) == 2
                and isinstance(p[0], str) and isinstance(p[1], str)):
            return p
        raise TypeError(
            f"net()/connect() expect pin references from handle.pin('name'); got {p!r}")

    def net(self, net_id, *pins, weight=1.0, color=None):
        """Declare an electrical net joining the given pins (``handle.pin('name')``)."""
        refs = frozenset(self._as_ref(p) for p in pins)
        self._route_nets.append((net_id, refs, weight))
        if color is not None:
            self._net_colors[net_id] = color
        return self

    def connect(self, a, b, *, weight=1.0, color=None):
        """Two-pin sugar: connect ``a`` to ``b``. Chained connects sharing a pin merge
        into one net (union-find in :meth:`_build_problem`)."""
        self._route_edges.append((self._as_ref(a), self._as_ref(b), weight, color))
        return self

    def _resolve_nets(self):
        """Explicit net() groups, plus connect() edges closed into nets via union-find."""
        nets = [(nid, set(refs), w) for (nid, refs, w) in self._route_nets]
        if self._route_edges:
            parent = {}

            def find(p):
                parent.setdefault(p, p)
                while parent[p] != p:
                    parent[p] = parent[parent[p]]
                    p = parent[p]
                return p

            groups, colors = {}, {}
            for a, b, w, color in self._route_edges:
                parent[find(a)] = find(b)
            for a, b, w, color in self._route_edges:
                groups.setdefault(find(a), set()).update((a, b))
                if color is not None:
                    colors[find(a)] = color
            for i, (root, refs) in enumerate(sorted(groups.items()), 1):
                nid = f"net{i}"
                nets.append((nid, refs, 1.0))
                if root in colors:
                    self._net_colors[nid] = colors[root]
        return [(nid, frozenset(refs), w) for (nid, refs, w) in nets]

    def _build_problem(self):
        """Translate registered components + declared nets into router inputs."""
        R = self._ensure_router()
        instances = []
        for c in self._route_components:
            ox, oy = c.origin
            pindefs = tuple(R.PinDef(name, (wx - ox, wy - oy))
                            for name, (wx, wy) in c.pins.items())
            keepouts = tuple(R.Rect.of(*ko) for ko in c.keepouts)
            ctype = R.ComponentType(c.id, pins=pindefs, keepouts=keepouts,
                                    internal=tuple(c.internal))
            instances.append(R.ComponentInstance(c.id, ctype, origin=c.origin, locked=c.locked))
        netlist = [R.Net(nid, refs, weight=w) for (nid, refs, w) in self._resolve_nets()]
        board = R.Board(w=self.board_width, h=self.board_height)
        return board, instances, netlist

    def _signature(self, board, instances, netlist, seed, weights):
        """Hashable key identifying the solve. Excludes unlocked origins (solver-chosen),
        so the same board rendered in three views hits the cache after the first solve."""
        comp_sig = tuple(sorted(
            (i.id, i.locked, i.origin if i.locked else None, i.flipped,
             tuple(sorted((p.local_id, p.offset) for p in i.type.pins)),
             tuple(sorted((r.x0, r.y0, r.x1, r.y1) for r in i.type.keepouts)),
             tuple(sorted(tuple(sorted(g)) for g in i.type.internal)))
            for i in instances))
        net_sig = tuple(sorted((n.id, tuple(sorted(n.pins)), n.weight) for n in netlist))
        w = None if weights is None else (
            weights.w_len, weights.w_jmp, weights.w_cut, weights.w_x, weights.w_y)
        return (board.w, board.h, comp_sig, net_sig, seed, w)

    def autoroute(self, *, seed=0, weights=None, options=None, net_colors=None,
                  show_cuts=True, show_keepouts=False, on_infeasible="partial"):
        """Solve the declared netlist and draw jumpers/cuts (and auto-placed parts).

        Idempotent across views: the solve is cached by signature, so calling this inside a
        draw lambda that runs once per view solves only the first time. Returns the
        router ``Result`` (status, cost, validation, per-net status)."""
        R = self._ensure_router()
        board, instances, netlist = self._build_problem()
        wobj = R.Weights(**weights) if isinstance(weights, dict) else weights
        sig = self._signature(board, instances, netlist, seed, wobj)
        result = self._route_cache.get(sig)
        if result is None:
            opts = options or R.RouteOptions(on_infeasible=on_infeasible)
            result = R.route(board, instances, netlist, weights=wobj, seed=seed, options=opts)
            self._route_cache[sig] = result
        placements = {p.instance_id: p for p in result.placements}
        for c in self._route_components:
            if not c.locked and c._redraw is not None:
                p = placements.get(c.id)
                if p is not None:
                    c._redraw(p.origin[0], p.origin[1], p.flipped)
        self._render_routing(result, net_colors=net_colors, show_cuts=show_cuts)
        if show_keepouts:
            # Shade keep-outs where the solver *placed* each part, not where it was drawn --
            # an unlocked part and its body keep-out move together (locked parts are unchanged).
            placed = [
                inst.moved(p.origin, p.flipped)
                if not inst.locked and (p := placements.get(inst.id)) is not None
                else inst
                for inst in instances
            ]
            self._render_keepouts(placed)
        self.last_result = result
        return result

    def _render_routing(self, result, net_colors=None, show_cuts=True):
        """Draw a router Result's jumpers + cuts onto this board (current view)."""
        colors = dict(self._net_colors)
        if net_colors:
            colors.update(net_colors)
        for net_id in sorted(result.routing.jumpers):
            color = colors.get(net_id)
            for j in result.routing.jumpers[net_id]:
                if color is None:
                    self.jumper(j.x, j.ya, j.x, j.yb)
                else:
                    self.jumper(j.x, j.ya, j.x, j.yb, color=color)
        if show_cuts:
            for x, y in sorted(result.physical_cuts):
                self.cut(x, y)

    def _shade_rect(self, x, y, w, h, color=(255, 140, 0)):
        """Draw a translucent, outlined rectangle (the keep-out region style)."""
        self.color(*color)
        self.pdf.set_alpha(0.22)
        self._rect(x, y, w, h, "F")
        self.pdf.set_alpha(1.0)
        self._rect(x, y, w, h, "S")
        self.black()

    def _render_keepouts(self, instances, color=(255, 140, 0)):
        """Shade each instance's keep-out rectangles (e.g. a button body)."""
        for inst in instances:
            for r in inst.world_keepouts():
                self._shade_rect(r.x0 - 0.5, r.y0 - 0.5,
                                 r.x1 - r.x0 + 1, r.y1 - r.y0 + 1, color)

    # Canonical build/preview views. Each is a fixed set of begin_board(...) toggles; only
    # the position (`at`) and board size change per call. These are the exact arg-sets that
    # recurred verbatim across every hand-built project's drawBuild()/label block.
    def begin_view(self, view, board_width, board_height, *, at=(0, 0), title=None,
                  rotate=False, **overrides):
        """begin_board() with one of the canonical view presets (FRONT/BACK/DESIGN/LABEL).

        The preset supplies the show* toggles; you pass position and size. `title` defaults
        to the view name (blank for LABEL). Any preset toggle can be overridden by keyword
        (e.g. ``show_numbers=True`` to print jumper lengths on the FRONT view)."""
        kw = dict(self._VIEW_PRESETS[view])
        kw.update(overrides)
        if title is None:
            title = '' if view == 'LABEL' else view
        self.begin_board(board_width, board_height, at=at, rotate=rotate, title=title, **kw)

    def triptych(self, draw, board_width, board_height, *, pitch, y=0, y0=0, tight=False,
                 front_numbers=False, rotate=False):
        """Draw the FRONT / BACK / DESIGN three-up build sheet.

        `draw(sb)` is invoked once per view; `pitch` is the horizontal spacing between the
        three boards. `y` shifts this board group vertically (to stack several boards on one
        sheet) about a baseline `y0`. `tight` blanks the per-view titles (for multi-up
        sheets). `front_numbers` prints jumper lengths on the FRONT view."""
        yy = y - y0
        t = (lambda n: '' if tight else n)
        self.begin_view('FRONT', board_width, board_height, at=(-pitch, yy),
                       show_numbers=front_numbers, title=t('FRONT'), rotate=rotate)
        draw(self); self.end_board()
        self.begin_view('BACK', board_width, board_height, at=(0, yy),
                       title=t('BACK'), rotate=rotate)
        draw(self); self.end_board()
        self.begin_view('DESIGN', board_width, board_height, at=(pitch, yy),
                       title=t('DESIGN'), rotate=rotate)
        draw(self); self.end_board()

    def route_report(self, result=None, *, file=None):
        """Print the standard autoroute summary (status/routed/jumpers/cuts + unrouted nets).

        Uses ``self.last_result`` (set by :meth:`autoroute`) when no result is passed; a
        no-op for hand-routed boards that never called autoroute()."""
        r = result if result is not None else self.last_result
        if r is None:
            return
        routed = sum(1 for ns in r.net_status if ns.routed)
        print(f"status={r.status.value} valid={r.validation.ok} "
              f"routed={routed}/{len(r.net_status)} "
              f"jumpers={r.cost.num_jumpers} cuts={r.cost.num_cuts} cost={r.cost.total}",
              file=file)
        print(f"solves cached: {len(self._route_cache)}", file=file)
        for ns in r.net_status:
            if not ns.routed:
                print(f"  UNROUTED {ns.net_id}: {ns.reason}", file=file)

    def gen(self, pdf_name):
        """Write the board PDF to `pdf_name`, creating parent directories as needed."""
        return self.pdf.output(pdf_name)

    def gen_carrier(self, stl_name, board_thickness=1.7, nozzle=0.7, rotate=False,
                    runner=None):
        """Render a 3D-printable carrier for this board to `stl_name`, via OpenSCAD.

        The carrier is a shallow tray the finished board slots into. Sizing comes from
        the board's own dimensions plus the thickness of the stock and your printer's
        nozzle width.

        Requires the ``openscad`` binary on PATH, and the BOSL OpenSCAD library that
        ``Carrier.scad`` includes. `runner` replaces the subprocess call, for tests.

        Raises:
          RuntimeError: if openscad is missing, or exits non-zero.
        """
        board_width = self.board_width
        board_height = self.board_height
        if rotate:
            board_width, board_height = board_height, board_width

        scad = files("stripboard.data") / "Carrier.scad"
        argv = [
            "openscad", str(scad),
            "-D", f"columns={board_width}",
            "-D", f"rows={board_height}",
            "-D", f"boardThickness={board_thickness}",
            "-D", f"nozzle={nozzle}",
            "-o", str(stl_name),
        ]
        if runner is not None:
            return runner(argv)

        exe = shutil.which("openscad")
        if exe is None:
            raise RuntimeError(
                "gen_carrier() needs the 'openscad' binary on PATH. Install OpenSCAD "
                "(https://openscad.org) along with its BOSL library, or pass "
                "carrier=False."
            )
        argv[0] = exe

        target = Path(stl_name)
        if target.parent != Path():
            target.parent.mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"openscad failed (exit {proc.returncode}) building {stl_name}."
                + (f"\n{detail}" if detail else "")
            )
        return target

    def _cap_bbox(self, kind):
        """Return (paths, xmin, xmax, ymin, ymax) for the captured strokes, or raise."""
        paths = [p for p in self._cap_paths if len(p) >= 2]
        if not paths:
            raise ValueError(f"{kind}: no captured geometry -- "
                             "render a view with _cap_on=True first (see _gcode_render).")
        xs = [x for p in paths for x, _ in p]
        ys = [y for p in paths for _, y in p]
        return paths, min(xs), max(xs), min(ys), max(ys)

    def gen_gcode(self, name, *, power=1000, feed=700, passes=1, pitch_mm=2.54,
                  origin=(0.0, 0.0), mirror=False, flip_y=True, dynamic=True, frame=False,
                  laser_mode=True):
        """Write the captured LABEL strokes as GRBL laser g-code (mm) to `name`.

        Consumes ``self._cap_paths`` (filled while ``self._cap_on`` during a LABEL render;
        see :func:`_gcode_render`). Paths are in board-grid (hole) units; they are
        bbox-normalised, optionally X-mirrored (``mirror``, to etch the board flipped) and
        Y-flipped (``flip_y``: grid rows run top->down, laser Y runs bottom->up), scaled by
        ``pitch_mm`` (2.54 mm/hole), then offset by ``origin`` (mm). Emits M4 dynamic power
        (recommended for engraving) unless ``dynamic=False`` (M3), repeated ``passes`` times;
        ``frame=True`` traces the bounding box once at low power first for alignment.
        Unless ``laser_mode=False``, emits ``$32=1`` at the top so the controller enters
        GRBL laser mode automatically (accepted at job start while GRBL is Idle)."""
        paths, xmin, xmax, ymin, ymax = self._cap_bbox("gen_gcode")
        w = xmax - xmin

        def to_mm(pt):
            x, y = pt
            nx = (w - (x - xmin)) if mirror else (x - xmin)
            ny = (ymax - y) if flip_y else (y - ymin)
            return (nx * pitch_mm + origin[0], ny * pitch_mm + origin[1])

        mm_paths = [[to_mm(pt) for pt in p] for p in paths]
        on = "M4" if dynamic else "M3"
        lines = [
            "; GRBL laser g-code generated by stripboard",
            f"; power=S{power} feed={feed} passes={passes} pitch_mm={pitch_mm} "
            f"mirror={mirror} flip_y={flip_y} dynamic={dynamic} laser_mode={laser_mode}",
        ]
        if laser_mode:
            # Enable GRBL laser mode as part of the job. $-settings are accepted only while
            # GRBL is Idle, which it is here (before any motion). Persists to the controller.
            lines.append("$32=1")
        lines += ["G21", "G90", "G94", "M5", "S0"]

        if frame:
            (fx0, fy0), (fx1, fy1) = to_mm((xmin, ymin)), to_mm((xmax, ymax))
            lo, hi = min(fx0, fx1), max(fx0, fx1)
            blo, bhi = min(fy0, fy1), max(fy0, fy1)
            fp = max(1, power // 40)
            lines += ["; --- framing pass (low power bounding box) ---",
                      f"G0 X{lo:.3f} Y{blo:.3f}", f"M3 S{fp}",
                      f"G1 X{hi:.3f} Y{blo:.3f} F{feed}", f"G1 X{hi:.3f} Y{bhi:.3f}",
                      f"G1 X{lo:.3f} Y{bhi:.3f}", f"G1 X{lo:.3f} Y{blo:.3f}", "M5"]

        for _ in range(max(1, passes)):
            for p in mm_paths:
                x0, y0 = p[0]
                lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
                lines.append(f"{on} S{power}")
                lines.append(f"G1 X{p[1][0]:.3f} Y{p[1][1]:.3f} F{feed}")
                lines.extend(f"G1 X{x:.3f} Y{y:.3f}" for x, y in p[2:])
                lines.append("M5")

        lines += ["M5", "G0 X0 Y0"]
        target = Path(name)
        if target.parent != Path():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {name}: {len(mm_paths)} paths, "
              f"{w*pitch_mm:.1f} x {(ymax-ymin)*pitch_mm:.1f} mm")

    def gen_svg(self, name, *, pitch_mm=2.54, stroke_mm=0.15):
        """Write the captured strokes as an SVG (mm) for vector import into LightBurn etc."""
        paths, xmin, xmax, ymin, ymax = self._cap_bbox("gen_svg")
        w, h = (xmax - xmin) * pitch_mm, (ymax - ymin) * pitch_mm

        def pt(p):
            return f"{(p[0]-xmin)*pitch_mm:.3f},{(ymax-p[1])*pitch_mm:.3f}"

        polys = "\n".join(f'  <polyline points="{" ".join(pt(q) for q in p)}"/>'
                          for p in paths)
        target = Path(name)
        if target.parent != Path():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.3f}mm" '
            f'height="{h:.3f}mm" viewBox="0 0 {w:.3f} {h:.3f}">\n'
            f'<g fill="none" stroke="black" stroke-width="{stroke_mm}" '
            f'stroke-linecap="round" stroke-linejoin="round">\n{polys}\n</g>\n</svg>\n',
            encoding="utf-8")
        print(f"wrote {name}: {len(paths)} paths, {w:.1f} x {h:.1f} mm")

    def _push(self):
        self._out('q')
        self._cap_ctm.append(self._cap_ctm[-1])

    def _pop(self):
        self._out('Q')
        if len(self._cap_ctm) > 1:
            self._cap_ctm.pop()

    def _translate(self, x, y):
        self._out('1 0 0 1 %.2F %.2F cm' % (x,y))
        self._cap_op(transform.translation(x, y))

    def _rotate(self, angle):
        angle = angle * 3.1415/180
        c = math.cos(angle)
        s = math.sin(angle)
        self._out('%.5F %.5F %.5F %.5F 0 0 cm' % (c,s,-s,c))
        self._cap_op(transform.rotation(c, s))

    def _flip_y(self):
        self._out('1 0 0 -1 0 0 cm')
        self._cap_op(transform.FLIP_Y)

    def _flip_x(self):
        self._out('-1 0 0 1 0 0 cm')
        self._cap_op(transform.FLIP_X)

    def _scale(self, scale_x, scale_y=None):
        if scale_y==None: scale_y = scale_x
        self._out('%.5F 0 0 %.5F 0 0 cm' % (scale_x, scale_y))
        self._cap_op(transform.scaling(scale_x, scale_y))

    def line_width(self, w):
        self._out('%.2F w' % (w))


def _rows(h):
    """Row count for a height given as a row letter ('Z' -> 26) or an int (26 -> 26)."""
    return ord(h) - 64 if isinstance(h, str) else h


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
    opts = {'name': carrier} if isinstance(carrier, str) else (carrier if isinstance(carrier, dict) else {})
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
    opts = dict(gcode) if isinstance(gcode, dict) else ({'name': gcode} if isinstance(gcode, str) else {})
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

