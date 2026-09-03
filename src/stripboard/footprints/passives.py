"""Two-lead and three-lead discretes: caps, resistors, LEDs, diodes, transistors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from .._state import BoardState as _Base
else:
    _Base = object

__all__ = ["PassivesMixin"]


class PassivesMixin(_Base):
    def radial(self, x, y, l, upside_down=False):
        y = self.row(y)
        self.jdot(x,y)
        self.jdot(x,y+l)
        r=l/2+0.5
        if self.show_components:
            self._ellipse(x,y+(l/2),r,r,f='S')

    def axial(self, x, y, l=1):
        y = self.row(y)
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
        if not self.show_components:
            return
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
                ox, oy - l if flip else oy, val, upside_down ^ flip, l,
                label_scale=label_scale, emit=True))

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
        if not self.show_components:
            return
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
