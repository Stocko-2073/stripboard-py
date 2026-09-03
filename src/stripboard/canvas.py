"""Drawing primitives and the graphics state.

The bottom layer: everything above this composes rectangles, lines, ellipses and arcs
out of these, and every one of them also feeds the stroke capture that the g-code and
SVG exporters consume. The transform methods emit PDF ``cm`` operators and update the
parallel capture CTM in lockstep -- see :mod:`stripboard.transform`.
"""

from __future__ import annotations

import math

from . import transform
from .geometry import KAPPA

__all__ = ["CanvasMixin"]


class CanvasMixin:
    def _out(self, s):
        self.pdf.out(s)

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
        if self.show_components:
            self._ellipse(x,y,0.25,0.25,f)
        elif self.show_crosses:
            self._ellipse(x,y,0.1,0.1,f)

    def polyline(self, poly, f='S'):
        pdf = self.pdf
        for i in range(0, len(poly), 2):
            op = 'm' if i == 0 else 'l'
            pdf.out('%.2f %.2f %s ' % (poly[i + 0], poly[i + 1], op))
        pdf.out(f)
        if self._cap_on and f == 'S':
            self._cap_add([(poly[i], poly[i + 1]) for i in range(0, len(poly) - 1, 2)])

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
        self._out('%.2F w' % (w))
