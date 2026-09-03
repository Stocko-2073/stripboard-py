"""SIP and DIP footprints.

Each is a renderer (``_draw_*``) paired with a pure-geometry twin (``*_pins``) that
returns the hole map without drawing. The pair exists because the autorouter needs a
footprint for a part it may not have placed yet, and because an auto-placed part has to
be redrawn once the solver picks its position.
"""

from __future__ import annotations

import math

__all__ = ["IcsMixin"]


class IcsMixin:
    def _draw_sip(self, x, y, l, name, upside_down=False, pins=None, flip=False,
                  mod=1, width=1, label_scale=1.0, emit=True):
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
            if self.show_components:
                self._ellipse(x,y+l-1,0.5,0.5,'S')
            if pins is not None:
                p = 0
                for yy in reversed(range(0, l)):
                    if flip:
                        self.rtext((x - 0.4 - label_scale), yy + y, pins[p], x_scale=label_scale)
                    else:
                        self.text((x + 0.4 + label_scale), yy + y, pins[p], x_scale=label_scale)
                    p += 1
        else:
            if self.show_components:
                self._ellipse(x,y,0.5,0.5,'S')
            if pins is not None:
                p = 0
                lp = len(pins)
                for yy in range(0, l):
                    if p < lp:
                        if flip:
                            self.rtext((x - 0.4 - label_scale), yy + y,
                                       pins[p], x_scale=label_scale)
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

    def sip(self, x, y, l, name="", upside_down=False, pins=None, flip=False,
            mod=1, width=1, label_scale=1.0, locked=True, ref=None):
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

    def _draw_dip(self, x, y, w, h, name="", upside_down=False, pins=None,
                  labels_inside=True, label_offset=0, label_scale=0.78, mod=1,
                  skip_pins=None, emit=True):
        y = self.row(y)
        skip_pins = () if skip_pins is None else skip_pins
        pinmap = self._dip_pins(x, y, w, h, pins, upside_down, mod, skip_pins)
        if not emit:
            return pinmap

        self.box(x + 0.5, y - 0.5, w - 1, h)
        for yy in range(0, h, mod):
            skipPin = yy+1 in skip_pins
            if not skipPin:
                if self.show_components:
                    self.wire(x, y + yy, x + 0.5, y + yy)
                self.dot(x, y + yy)
        for yy in range(h-1, -1, -mod):
            if h*2-yy not in skip_pins:
                if self.show_components:
                    self.wire(x + w, y + yy, x + w - 0.5, y + yy)
                self.dot(x + w, y + yy)


        if upside_down:
            if self.show_components:
                self._ellipse(x + w, y + h - 1, 0.5, 0.5, 'S')
            if pins is not None:
                p = 0
                for yy in reversed(range(0, h, mod)):
                    if labels_inside:
                        self.rtext((x + w - label_scale - 0.3), yy + y,
                                   pins[p], x_scale=label_scale)
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
            if self.show_components:
                self._ellipse(x,y,0.5,0.5,'S')
            if pins is not None:
                p = 0
                lp = len(pins)
                for yy in range(0, h, mod):
                    if p < lp:
                        if labels_inside:
                            self.text((x + label_scale + 0.3), yy + y, pins[p], x_scale=label_scale)
                        else:
                            self.rtext((x - label_scale - 0.1), yy + y,
                                       pins[p], x_scale=label_scale)
                    p += 1
                for yy in reversed(range(0, h, mod)):
                    if p < lp:
                        if labels_inside:
                            self.rtext((x + w - label_scale - 0.3), yy + y, pins[p],
                                       x_scale=label_scale)
                        else:
                            self.text((x + w + label_scale + 0.1), yy + y, pins[p],
                                      x_scale=label_scale)
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

    def dip(self, x, y, w, h, name="", upside_down=False, pins=None,
            labels_inside=True, label_offset=0, label_scale=0.78, mod=1,
            skip_pins=None, locked=True, ref=None):
        """Draw a DIP footprint and return a :class:`Component` handle for autorouting."""
        ry = self.row(y)
        kwargs = dict(name=name, upside_down=upside_down, pins=pins, labels_inside=labels_inside,
                      label_offset=label_offset, label_scale=label_scale,
                      mod=mod, skip_pins=skip_pins)
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
        if not self.show_components:
            return
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
