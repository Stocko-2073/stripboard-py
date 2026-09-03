"""555 astable LED blinker -- routed by hand.

The same circuit as ``blinker_555.py``, but the copper is spelled out instead of solved
for: ``sb.jumper(...)`` for each wire on the component side, ``sb.cut(...)`` for each
track cut on the copper side, and ``sb.trace(...)`` to flood-fill and colour a net in the
DESIGN view so you can check connectivity by eye before you pick up a soldering iron.

This is the workflow when you want full control, or when you are transcribing a layout
you already have on paper. A practical middle road is to let ``autoroute()`` find a
starting layout, then paste its jumpers and cuts in here and hand-tune -- which is exactly
how the routing below was produced.

Run:  python examples/blinker_555_hand.py   ->   blinker_555_hand.pdf
"""

from stripboard import project

designing = True

PINS_555 = ["GND", "TRIG", "OUT", "RESET", "CTRL", "THRESH", "DISCH", "VCC"]


def draw(sb):
    sb.text(1, "A", "555 BLINKER")

    # Components -- identical placement to blinker_555.py.
    sb.terminal(2, "C", 2)                          # 1 = +V, 2 = GND
    sb.dip(6, "F", 3, 4, "555", pins=PINS_555)
    sb.resist(13, "F", "10K", l=3)
    sb.resist(16, "F", "47K", l=3)
    sb.resist(13, "N", "330", l=3)
    sb.cap(3, "N")
    sb.led(16, "N")

    # Jumper wires: vertical links on the component side, crossing between strips.
    sb.jumper(8, "C", 8, "F", color="r")            # VCC: terminal -> pin 8
    sb.jumper(5, "C", 5, "I", color="r")            # VCC: -> RESET
    sb.jumper(4, "D", 4, "F", color="k")            # GND: terminal -> pin 1
    sb.jumper(2, "F", 2, "O", color="k")            # GND: -> cap
    sb.jumper(8, "I", 8, "O", color="k")            # GND: CTRL -> LED cathode
    sb.jumper(15, "F", 15, "G")                     # DISCH: R1 -> R2
    sb.jumper(12, "G", 12, "I")                     # DISCH: pin 7 -> R1
    sb.jumper(4, "G", 4, "J")                       # TIMING
    sb.jumper(10, "H", 10, "J")                     # TIMING: THRESH
    sb.jumper(15, "I", 15, "J")                     # TIMING: R2
    sb.jumper(5, "J", 5, "N")                       # TIMING: -> cap
    sb.jumper(7, "H", 7, "N")                       # OUT: pin 3 -> R3
    sb.jumper(15, "N", 15, "Q", color="y")          # LED: R3 -> anode

    # Track cuts: break the copper strip so the two halves become separate nets.
    for x, y in [(7, "F"), (8, "G"), (8, "H"), (7, "I"), (11, "I"),
                 (14, "F"), (14, "I"), (6, "N"), (14, "N")]:
        sb.cut(x, y)

    # Connectivity check: flood-fill from one pin of each net.
    sb.trace(8, "C")        # VCC
    sb.trace(4, "D")        # GND
    sb.trace(12, "G")       # DISCH
    sb.trace(10, "H")       # TIMING
    sb.trace(7, "H")        # OUT
    sb.trace(15, "Q")       # LED


if __name__ == "__main__":
    project(draw, name="blinker_555_hand", width=18, height="T", designing=designing)
