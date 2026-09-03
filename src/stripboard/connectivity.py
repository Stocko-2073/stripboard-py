"""Net tracing: flood-fill a net through strips, cuts and jumpers, and colour it.

`trace` is the connectivity check you run before soldering. Starting from one hole it
walks the copper strip outwards, stopping at cuts, hopping along jumpers, and shading
every hole it reaches -- so the DESIGN view shows each net as one contiguous colour and a
mistake shows up as a net that is the wrong shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .drc import ShortCircuitWarning, TraceCollisionWarning
from .drc import warn as _warn

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from ._state import BoardState as _Base
else:
    _Base = object

__all__ = ["ConnectivityMixin"]


class ConnectivityMixin(_Base):
    def trace_jumper(self, x, y, x2, y2, color):
        if not self.show_jumpers:
            return
        y = self.row(y)
        if(isinstance(y2, str)):
            y2 = ord(y2) - 64
        self.jdot(x, y)
        self.jdot(x2, y2)
        self.pdf.set_draw_color(*color)
        self.wire(x, y, x2, y2)

        dist = int(((x2 - x)**2 + (y2 - y)**2)**0.5)
        if dist > 1 and self.show_numbers:
            label = str(dist)
            self.pdf.set_fill_color(255)
            self._rect(
                (x + (x2 - x) / 2)-0.5,
                (y + (y2 - y) / 2)-0.5,
                1,
                len(label),
                "F"
            )
            self.pdf.set_draw_color(*color)
            self.vtext(x + (x2 - x) / 2, y + (y2 - y) / 2, label)

        self.pdf.set_draw_color(*color)
        self.pdf.set_fill_color(0)

    def trace(self, x, y, color=None):
        if not self.show_traces:
            return
        y = self.row(y)
        marked: list[tuple[float, float]] = []
        if color is None:
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
