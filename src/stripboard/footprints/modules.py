"""Pre-drawn footprints for common dev boards (XIAO, RP2040, ESP32, Digispark)."""

from __future__ import annotations

__all__ = ["ModulesMixin"]


class ModulesMixin:
    def esp32minikit(self, x, y):
        """Draw an ESP32 MiniKit footprint with its top-left pin at (x, y).

        A composite footprint: it draws sub-primitives directly rather than registering
        parts, so it returns no handle and cannot be autorouted.
        """
        y = self.row(y)
        self._draw_dip(x, y, 9, 10, "ESP32", False, [
            '7', '15', '5V', 'G', '16', '17', 'SDA', 'SCL', 'RX', 'TX',
            'RST', '36', '26', 'SCK', 'MISO', 'MOSI', 'CS0', '3V3', '13', '10'
        ],
        label_offset=0.5,
        label_scale=0.8,
        skip_pins=None
        )
        self._draw_sip(x - 1, y, 10, "", False, flip=True,
                       pins=['6', '8', '2', '0', '4', '12', '32', '25', '27', 'GND'],
                       label_scale=0.8)
        self._draw_sip(x + 10, y, 10, "", True, flip=False,
                       pins=['GND', 'NC', '39', '35', '33', '34', '14', 'NC', '9', '11'],
                       label_scale=0.8)

    def rp2040(self, x, y, locked=True, ref=None):
        # Seeed studio XIAO RP2040 module -> builder returning a Component handle.
        ry = self.row(y)
        pins = ['D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'TX',
                'RX', 'D8', 'D9', 'D10', '3V3', 'GND', '5V']

        def draw(ox, oy, flip):
            dx = ox - 6 if flip else ox
            dy = oy - 6 if flip else oy  # h=7 -> h-1=6
            pm = self._draw_dip(dx, dy, 6, 7, "RP2040", upside_down=flip,
                                pins=pins, label_scale=0.6, emit=True)
            self.box(dx + 1.5, (dy + 6.3) if flip else (dy - 1.5), 3, 1.2, 'F')
            return pm

        pinmap = draw(x, ry, False) if locked else self._dip_pins(x, ry, 6, 7, pins, False, 1, [])
        return self._register(ref or "RP2040", pinmap, (x, ry), locked, redraw=draw)

    def xiao(self, x, y, upside_down=False, labels_inside=True, label_offset=0,
             label_scale=0.6, mod=1, skip_pins=None, locked=True, ref=None):
        # Seeed studio XIAO RP2040 module -> builder returning a Component handle.
        ry = self.row(y)
        pins = ['D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'TX',
                'RX', 'D8', 'D9', 'D10', '3V3', 'GND', '5V']

        def draw(ox, oy, flip):
            ud = upside_down ^ flip
            dx = ox - 6 if flip else ox
            dy = oy - 6 if flip else oy  # h=7 -> h-1=6
            pm = self._draw_dip(dx, dy, 6, 7, "XIAO", upside_down=ud, pins=pins,
                                labels_inside=labels_inside, label_offset=label_offset,
                                label_scale=label_scale, mod=mod, skip_pins=skip_pins, emit=True)
            self.box(dx + 1.5, (dy + 6.3) if ud else (dy - 1.5), 3, 1.2, 'F')
            return pm

        pinmap = draw(x, ry, False) if locked else self._dip_pins(x, ry, 6, 7, pins, upside_down,
                      mod, skip_pins)
        return self._register(ref or "XIAO", pinmap, (x, ry), locked, redraw=draw)

    def digispark(self, x, y,show_port=False,ground_only=False):
        y = self.row(y)
        self.box(x-0.5,y-0.5,8,7)
        self._draw_sip(x,y+1,6,name="",pins=['D','2','C','A','1','R'])
        if ground_only:
            self._draw_sip(x+5,y,1,name="",pins=['GND'],flip=True)
        if not ground_only:
            self._draw_sip(x+3,y,1,name="",pins=['I'],flip=True)
            self._draw_sip(x+4,y,1,name="")
            self._draw_sip(x+5,y,1,name="",pins=['+'])
        if show_port:
            self.box(x+5,y+1.5,3,3,'F')

    def usb_breakout(self, x, y, show_port=False):
        y = self.row(y)
        self.box(x-0.5,y-0.5,6,5)
        self._draw_sip(x,y,5,name="",pins=['G','ID','D+','D-','5V'])
        if show_port:
            self.box(x+3.5,y+0.5,2,3,'F')
