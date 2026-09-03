"""555 astable LED blinker -- routed by the autorouter.

Declare what is *electrically* true with ``sb.net(...)`` and let ``sb.autoroute()`` work
out the copper: which strips carry which net, where the jumper wires go, and which tracks
have to be cut. Compare with ``blinker_555_hand.py``, which is the same circuit with the
jumpers and cuts written out by hand.

    NE555 astable, ~1.4 Hz at 50% duty:
      R1  VCC -> DISCH(7)          10k
      R2  DISCH(7) -> THRESH(6)    47k, tied to TRIG(2)
      C1  TRIG(2) -> GND           10uF
      R3  OUT(3) -> LED anode      330R, LED cathode to GND
      RESET(4) -> VCC, CTRL(5) -> GND

Run:  python examples/blinker_555.py   ->   blinker_555.pdf
"""

from stripboard import project

# True renders one DESIGN page for fast iteration; False renders the FRONT/BACK/DESIGN
# build sheet you actually solder from.
designing = True

PINS_555 = ["GND", "TRIG", "OUT", "RESET", "CTRL", "THRESH", "DISCH", "VCC"]


def draw(sb):
    sb.text(1, "A", "555 BLINKER")

    pwr = sb.terminal(2, "C", 2)                    # 1 = +V, 2 = GND
    u1 = sb.dip(6, "F", 3, 4, "555", pins=PINS_555)
    r1 = sb.resist(13, "F", "10K", l=3)
    r2 = sb.resist(16, "F", "47K", l=3)
    r3 = sb.resist(13, "N", "330", l=3)
    c1 = sb.cap(3, "N")
    led = sb.led(16, "N")

    sb.net("VCC", pwr.pin(1), u1.pin("VCC"), u1.pin("RESET"), r1.pin(1), color="r")
    sb.net("GND", pwr.pin(2), u1.pin("GND"), u1.pin("CTRL"),
           c1.pin(2), led.pin("K"), color="k")
    sb.net("DISCH", u1.pin("DISCH"), r1.pin(2), r2.pin(1))
    sb.net("TIMING", u1.pin("THRESH"), u1.pin("TRIG"), r2.pin(2), c1.pin(1))
    sb.net("OUT", u1.pin("OUT"), r3.pin(1))
    sb.net("LED", r3.pin(2), led.pin("A"), color="y")

    sb.autoroute(seed=0)


if __name__ == "__main__":
    project(draw, name="blinker_555", width=18, height="T", designing=designing)
