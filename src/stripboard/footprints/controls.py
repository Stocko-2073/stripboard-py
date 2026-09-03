"""Human-operated parts: potentiometers and pushbuttons."""

from __future__ import annotations

__all__ = ["ControlsMixin"]


class ControlsMixin:
    def pot(self, x, y, upside_down=False):
        y = self.row(y)
        self.dot(x, y + 0)
        self.dot(x, y + 1)
        self.dot(x, y + 2)
        if not self.show_components:
            return
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

    def _draw_big_button(self, x, y, emit=True):
        y = self.row(y)
        pinmap = {'AL': (x, y), 'BL': (x, y + 2), 'AR': (x + 5, y), 'BR': (x + 5, y + 2)}
        if not emit:
            return pinmap
        self.dot(x, y)
        if self.show_components:
            self.wire(x, y, x + 0.5, y)
        self.dot(x, y + 2)
        if self.show_components:
            self.wire(x, y + 2, x + 0.5, y + 2)
        self.dot(x + 5, y)
        if self.show_components:
            self.wire(x + 5, y, x + 5 - 0.5, y)
        self.dot(x + 5, y + 2)
        if self.show_components:
            self.wire(x + 5, y + 2, x + 5 - 0.5, y + 2)
        if self.show_components:
            self.box(x + 0.5, y - 1, 4, 4)
        if self.show_components:
            self._ellipse(x + 2.5, y + 1, 1.5, 1.5)
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
        if self.show_components:
            self.wire(x,y,x+0.5,y)
        self.dot(x+3,y)
        if self.show_components:
            self.wire(x+3,y,x+2.5,y)
        self.dot(x,y+2)
        if self.show_components:
            self.wire(x,y+2,x+0.5,y+2)
        self.dot(x+3,y+2)
        if self.show_components:
            self.wire(x+3,y+2,x+2.5,y+2)
        if self.show_components:
            self.box(x+0.5,y,2,2)
        if self.show_components:
            self._ellipse(x+1.5,y+1,0.75,0.75)
