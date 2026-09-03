"""`StripBoard`: the object a board file draws on.

One instance is a whole *sheet*, not a single board. ``begin_board``/``end_board``
bracket each board placed on it, and ``triptych`` puts three views of the same board side
by side, which is why the class carries page-level state (the PDF, the transform stack,
the autoroute cache) separately from per-board state (components, connections, nets)
that ``begin_board`` resets.

The class itself is a facade: its behaviour is composed from mixins, each in its own
module. That split is by concern -- drawing, text, footprints, wiring, connectivity,
netlist, autorouting, output -- and the mixins share `self` rather than collaborating
through interfaces, which is an honest reflection of how much mutable render state they
genuinely have in common.
"""

from __future__ import annotations

from . import transform
from .autoroute import AutorouteMixin
from .canvas import CanvasMixin
from .connectivity import ConnectivityMixin
from .export.generate import ExportMixin
from .font import VECTOR_CHARS
from .footprints import FootprintsMixin
from .geometry import parse_row
from .netlist import NetlistMixin
from .palette import COLORS, WIRE_COLORS
from .pdf import PdfDocument
from .text import TextMixin
from .views import VIEW_PRESETS
from .wiring import WiringMixin

__all__ = ["StripBoard"]


class StripBoard(
    CanvasMixin,
    TextMixin,
    FootprintsMixin,
    WiringMixin,
    ConnectivityMixin,
    NetlistMixin,
    AutorouteMixin,
    ExportMixin,
):
    """A board being drawn: geometry, components, wiring, and the PDF it renders to.

    See :func:`stripboard.project` for the usual entry point; construct this directly
    when you need several boards on one sheet or a non-standard page.
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
        if not show_crosses:
            self.show_traces = False
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
        if self.rotate:
            self._rotate(90)
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
        if not show_crosses:
            self.show_traces = False
        self.show_jumpers = show_jumpers
        self.show_components = show_components
        self.show_drills = show_drills

    def end_board(self):
        self._pop()

    def row(self, y):
        """Coerce a row given as a letter (``'A'`` -> 1) or an int to an int."""
        return parse_row(y)

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
        def t(name):
            return '' if tight else name

        self.begin_view('FRONT', board_width, board_height, at=(-pitch, yy),
                       show_numbers=front_numbers, title=t('FRONT'), rotate=rotate)
        draw(self)
        self.end_board()
        self.begin_view('BACK', board_width, board_height, at=(0, yy),
                       title=t('BACK'), rotate=rotate)
        draw(self)
        self.end_board()
        self.begin_view('DESIGN', board_width, board_height, at=(pitch, yy),
                       title=t('DESIGN'), rotate=rotate)
        draw(self)
        self.end_board()
