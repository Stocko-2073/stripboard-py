"""Things wires and plugs attach to: headers, jacks, screw terminals, power rails."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from .._state import BoardState as _Base
else:
    _Base = object

__all__ = ["ConnectorsMixin"]


class ConnectorsMixin(_Base):
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
