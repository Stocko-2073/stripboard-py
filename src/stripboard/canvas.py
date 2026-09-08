"""Drawing primitives and the graphics state.

The bottom layer: everything above this composes rectangles, lines, ellipses and arcs
out of these, and every one of them also feeds the stroke capture that the g-code, SVG
and OpenSCAD exporters consume. The transform methods emit PDF ``cm`` operators and update the
parallel capture CTM in lockstep -- see :mod:`stripboard.transform`.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from . import transform
from .geometry import KAPPA

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from ._state import BoardState as _Base
else:
    _Base = object

__all__ = ["CanvasMixin"]


class CanvasMixin(_Base):
    def _out(self, s):
        self.pdf.out(s)

    def _cap_op(self, m_op):
        """Apply transform matrix m_op to the top of the capture CTM stack."""
        if self._cap_ctm:
            self._cap_ctm[-1] = transform.compose(m_op, self._cap_ctm[-1])

    def _cap_pt(self, x, y):
        return transform.apply(self._cap_ctm[-1], x, y)

    def _cap_hole(self, x, y):
        """Record a hole a lead passes through: a part pin, or a wire end.

        Every footprint marks its pins with dot() and every wire end with jdot(), so this
        is the complete set however the part was built -- and unlike a netlist it does not
        care whether the builder registers a component. Recorded whatever the view chooses
        to ink, because a lead occupies the hole either way.
        """
        if self._cap_on:
            self._cap_holes.append(self._cap_pt(x, y))

    def _cap_ink_add(self, kind, pts):
        """Record a painted shape, its colour and its place in the paint order.

        The 3D label needs what the page *looks* like, not just where its centrelines
        run: a filled component body is ink, and so is the box a glyph is knocked out
        of. Colour carries that because white is how this renderer erases -- a point is
        inked when the last shape covering it was black -- which is also why the order
        here is the order it was painted in.

        Marks drawn for the page rather than for the artwork are held off by
        `_cap_page_only`. Two of them: a pad is a ring of ink around a hole very nearly
        its own width, so it asks for a bead thinner than a nozzle can lay and the hole
        alone says the same thing; and the white box behind a glyph is there to blank the
        page under it, which a plate has nothing to do -- while cutting the shape it
        crosses down to a sliver.
        """
        if self._cap_on and not self._cap_page_only:
            width = (self._cap_width * transform.scale_factor(self._cap_ctm[-1])
                     if kind == 'S' else 0.0)
            self._cap_ink.append((kind, self.last_color == (255, 255, 255), width,
                                  [self._cap_pt(px, py) for px, py in pts]))

    def _cap_add(self, pts):
        """Record a stroked polyline (local-coord (x,y) pairs) into _cap_paths.

        The width goes in beside it, resolved through the capture CTM: a caller sets the
        width before the transforms that position the geometry, so the width that paints
        is the one it set scaled by the matrix in effect here. Text is the case that makes
        the difference -- a glyph sets one width and is then scaled to its point size.
        """
        if self._cap_on and len(pts) >= 2:
            self._cap_paths.append([self._cap_pt(px, py) for px, py in pts])
            self._cap_widths.append(
                self._cap_width * transform.scale_factor(self._cap_ctm[-1]))

    def _rect(self,x,y,w,h,f='S'):
        self._out('%.2F %.2F m %.2F %.2F l %.2F %.2F l %.2F %.2F l %.2F %.2F l %s' %
            (x,y, x+w,y, x+w,y+h, x,y+h, x,y, f))
        pts = [(x,y), (x+w,y), (x+w,y+h), (x,y+h), (x,y)]
        if self._cap_on and f == 'S':
            self._cap_add(pts)
        self._cap_ink_add('S' if f == 'S' else 'F', pts)

    def _line(self,x1,y1,x2,y2,f='S'):
        self._out('%.1F %.1F m %.1F %.1F l %s' % (x1,y1,x2,y2,f))
        if self._cap_on and 'F' not in f:
            self._cap_add([(x1,y1), (x2,y2)])
            self._cap_ink_add('S', [(x1,y1), (x2,y2)])

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
        if self._cap_on:
            n = 32
            poly = [(x + rx * math.cos(2*math.pi*i/n),
                     y + ry * math.sin(2*math.pi*i/n)) for i in range(n + 1)]
            if f == 'S':
                self._cap_add(poly)
            self._cap_ink_add('S' if f == 'S' else 'F', poly)

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
                    quad = [(x + rx*math.cos(t0 + (math.pi/2)*k/8),
                             y + ry*math.sin(t0 + (math.pi/2)*k/8)) for k in range(9)]
                    self._cap_add(quad)
                    self._cap_ink_add('S', quad)

    def box(self, x, y, w, h, f='S'):
        if not self.show_components:
            return
        y = self.row(y)
        self._rect(x,y,w,h,f)

    def wire(self, x, y, x2, y2):
        y = self.row(y)
        y2 = self.row(y2)
        self._line(x,y,x2,y2)

    def dot(self, x, y, f='F'):
        y = self.row(y)
        self._cap_hole(x, y)
        self._cap_page_only = True
        if self.show_components:
            self._ellipse(x,y,0.25,0.25,f)
        elif self.show_crosses:
            self._ellipse(x,y,0.1,0.1,f)
        self._cap_page_only = False

    def polyline(self, poly, f='S'):
        pdf = self.pdf
        for i in range(0, len(poly), 2):
            op = 'm' if i == 0 else 'l'
            pdf.out('%.2f %.2f %s ' % (poly[i + 0], poly[i + 1], op))
        pdf.out(f)
        if self._cap_on:
            pts = [(poly[i], poly[i + 1]) for i in range(0, len(poly) - 1, 2)]
            if f == 'S':
                self._cap_add(pts)
            self._cap_ink_add('S' if f == 'S' else 'F', pts)

    def white(self):
        self.pdf.set_draw_color(255)
        self.pdf.set_fill_color(255)
        self.last_color = (255,255,255)

    def black(self):
        self.pdf.set_draw_color(0)
        self.pdf.set_fill_color(0)
        self.last_color = (0,0,0)

    def grey(self, level=128):
        """Set both draw and fill colour to a grey level (0 black .. 255 white)."""
        if self.black_and_white:
            self.black()
            self.last_color = (0,0,0)
        else:
            self.pdf.set_draw_color(level)
            self.pdf.set_fill_color(level)
            self.last_color = (level, level, level)

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
        if scale_y is None:
            scale_y = scale_x
        self._out('%.5F 0 0 %.5F 0 0 cm' % (scale_x, scale_y))
        self._cap_op(transform.scaling(scale_x, scale_y))

    def line_width(self, w):
        self._cap_width = w
        self._out('%.2F w' % (w))
