"""Hand-routing primitives: jumper wires, track cuts, drilled holes, keep-outs.

This is the manual half of routing -- what you call when you are laying the copper out
yourself rather than declaring a netlist. `jumper` and `cut` are also what the autorouter
draws through once it has solved.
"""

from __future__ import annotations

import math

from .drc import JumperConflictWarning
from .drc import warn as _warn

__all__ = ["WiringMixin"]


class WiringMixin:
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
        if not self.show_drills:
            return
        y = self.row(y)
        self._ellipse(x,y,0.25,0.25,'F')
        self._ellipse(x,y,0.5,0.5,'S')

    def cut(self, x, y, y2=None):
        if not self.show_crosses:
            return
        y = self.row(y)
        if y2 is None:
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
        if not self.show_traces:
            return
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
