"""Text rendering with the built-in vector stroke font.

Four orientations (`text` horizontal, `vtext` rotated, `utext` upside down, `rtext`
right-aligned) all funnel into `draw_letter`, which scales a glyph from
:mod:`stripboard.font` onto the hole grid and strokes it. Because the glyphs are
polylines rather than a real font, the same geometry can be re-emitted as laser g-code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .drc import MissingGlyphWarning
from .drc import warn as _warn

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from ._state import BoardState as _Base
else:
    _Base = object

__all__ = ["TextMixin"]


class TextMixin(_Base):
    def vtext(self, x, y, text, y_scale=1.0):
        if not self.show_components:
            return
        y = self.row(y)
        chars = list(text)
        if self.rotate:
            chars.reverse()
        yy = 0
        for c in chars:
            self.draw_letter(x, y + yy, c, y_scale=y_scale)
            yy += y_scale

    def utext(self, x, y, text):
        if not self.show_components:
            return
        y = self.row(y)
        chars = list(text)
        if not self.rotate:
            chars.reverse()
        yy = 0
        for c in chars:
            self.draw_letter(x, y - yy, c)
            yy += 1

    def text(self, x, y, text, x_scale=1.0):
        if not self.show_components:
            return
        y = self.row(y)
        chars = list(text)
        xx = 0
        for c in chars:
            self.draw_letter(x + xx, y, c, x_scale=x_scale)
            xx += x_scale

    def rtext(self, x, y, text, x_scale=1.0):
        if not self.show_components:
            return
        y = self.row(y)
        chars = reversed(list(text))
        xx = 0
        for c in chars:
            self.draw_letter(x + xx, y, c, x_scale=x_scale)
            xx -= x_scale

    def draw_letter(self, x, y, c, x_scale=1.0, y_scale=1.0):
        xs = 0.8 / 5
        ys = 0.8 / 5
        y = self.row(y)

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

    def copyright(self,x,y):
        if not self.show_components:
            return
        y = self.row(y)
        self.line_width(0.15)
        self._push()
        self._translate(x,y)
        self._ellipse(0,0,0.4,0.4,'S')
        self._rotate(45)
        self._arc(0,0,0.18,0.18,tl=False)
        self._pop()
        self.line_width(0.2)

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
