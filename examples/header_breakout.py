"""I2C screw-terminal breakout, with a silkscreen label and laser g-code.

A deliberately simple board: a 4-way screw terminal broken out to a 0.1" pin header,
plus a power-on LED. Nothing needs a jumper to cross strips except the LED branch,
because a stripboard's copper already runs horizontally -- terminal pin and header pin on
the same row are connected for free. That is the whole trick of the format.

Its real job here is to demonstrate the output side. ``project()`` is asked for three
things beyond the board PDF:

* ``label=True``   -> ``header_breakout-label.pdf``, a black-and-white silkscreen
* ``gcode=True``   -> ``header_breakout.nc``, GRBL laser g-code that etches that
                      silkscreen onto the board top, plus an SVG for vector tools

Run:  python examples/header_breakout.py
"""

from stripboard import project

# False renders the FRONT/BACK/DESIGN build sheet and the label PDF; flip to True for a
# single-page DESIGN preview while you are still moving parts around. (The g-code is
# emitted either way -- it is derived from the label, not from the build sheet.)
designing = False


def draw(sb):
    sb.text(1, "A", "I2C BREAKOUT")

    # Screw terminal in, pin header out, on matching rows.
    sb.terminal(2, "C", 4)
    sb.header(11, "C", 4)

    for row, name in zip("CDEF", ("+5V", "GND", "SDA", "SCL")):
        sb.text(4.6, row, name, x_scale=0.6)

    # Power-on LED: +5V down to a free strip, through the resistor, into the LED,
    # and back up to ground.
    sb.jumper(8, "C", 8, "H", color="r")
    sb.resist(8, "H", "1K", l=1)
    sb.led(10, "I")
    sb.jumper(10, "D", 10, "J", color="k")

    sb.trace(2, "C")        # +5V
    sb.trace(2, "D")        # GND


if __name__ == "__main__":
    project(
        draw,
        name="header_breakout",
        width=13,
        height="J",
        designing=designing,
        label=True,
        gcode=dict(svg=True),
    )
