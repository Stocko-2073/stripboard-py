"""Independent §8 validator tests: forbidden cases rejected, permitted overlaps accepted."""

from __future__ import annotations

from stripboard.router.geometry import Rect
from stripboard.router.model import (
    Board,
    ComponentInstance,
    ComponentType,
    Jumper,
    Net,
    PinDef,
    Routing,
    Strip,
)
from stripboard.router.validation import validate

BOARD = Board(34, 26)
PTYPE = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def codes(res):
    return {v.code for v in res.violations}


def valid_layout():
    """A minimal fully-valid 2-pin net: strips on rows 4 & 8 joined by a jumper at x=5."""
    p1 = ComponentInstance("P1", PTYPE, origin=(3, 4))
    p2 = ComponentInstance("P2", PTYPE, origin=(3, 8))
    net = Net("N1", frozenset({("P1", "1"), ("P2", "1")}))
    r = Routing()
    r.add_strip(Strip(4, 3, 5, "N1"))
    r.add_strip(Strip(8, 3, 5, "N1"))
    r.add_jumper(Jumper(5, 4, 8, "N1"))
    return [p1, p2], [net], r


def test_valid_layout_passes():
    inst, nets, r = valid_layout()
    res = validate(BOARD, inst, nets, r)
    assert res.ok, res.summary()


# --- Rule 1: on board ----------------------------------------------------------------


def test_offboard_strip():
    inst, nets, r = valid_layout()
    r.strips["N1"][0] = Strip(4, 3, 40, "N1")
    assert "offboard_strip" in codes(validate(BOARD, inst, nets, r))


def test_offboard_jumper():
    inst, nets, r = valid_layout()
    r.jumpers["N1"][0] = Jumper(40, 4, 8, "N1")
    assert "offboard_jumper" in codes(validate(BOARD, inst, nets, r))


# --- Rule 4: forbidden overlaps + same-row gap ---------------------------------------


def test_same_row_gap_touching():
    inst, nets, r = valid_layout()
    r.add_strip(Strip(4, 6, 8, "N1"))  # touches [3,5] (xa=6 == 5+1)
    assert "same_row_gap" in codes(validate(BOARD, inst, nets, r))


def test_same_row_gap_one_column_ok():
    inst, nets, r = valid_layout()
    # add a separate same-net strip with a 1-column gap: valid (a cut lands between).
    r.add_strip(Strip(4, 7, 8, "N1"))  # gap column at x=6
    res = validate(BOARD, inst, nets, r)
    assert "same_row_gap" not in codes(res)


def test_pin_pin_overlap():
    inst, nets, r = valid_layout()
    # move P2 onto P1's hole
    inst[1] = ComponentInstance("P2", PTYPE, origin=(3, 4))
    assert "pin_pin" in codes(validate(BOARD, inst, nets, r))


def test_keepout_keepout_overlap():
    body = ComponentType("BOX", keepouts=(Rect.of(0, 0, 2, 2),))
    a = ComponentInstance("A", body, origin=(5, 5))
    b = ComponentInstance("B", body, origin=(6, 6))
    res = validate(BOARD, [a, b], [], Routing())
    assert "keepout_keepout" in codes(res)


def test_pin_keepout_overlap():
    body = ComponentType("BOX", keepouts=(Rect.of(0, 0, 2, 2),))
    box = ComponentInstance("B", body, origin=(5, 5))  # covers (5,5)..(7,7)
    pin = ComponentInstance("P1", PTYPE, origin=(6, 6))  # pin inside the box
    net = Net("N1", frozenset({("P1", "1")}))
    r = Routing()
    r.add_strip(Strip(6, 6, 6, "N1"))
    assert "pin_keepout" in codes(validate(BOARD, [box, pin], [net], r))


def test_jumper_keepout_overlap():
    inst, nets, r = valid_layout()
    body = ComponentInstance("B", ComponentType("BOX", keepouts=(Rect.of(0, 0, 0, 4),)), origin=(5, 4))
    # keep-out column x=5 rows 4..8 collides with jumper endpoint/arc at x=5
    assert "jumper_keepout" in codes(validate(BOARD, [*inst, body], nets, r))


def test_pin_jumper_overlap():
    inst, nets, r = valid_layout()
    # put a stray pin at a jumper endpoint (5,4)
    stray = ComponentInstance("P3", PTYPE, origin=(5, 4))
    nets2 = [Net("N1", frozenset({("P1", "1"), ("P2", "1")})), Net("N2", frozenset({("P3", "1")}))]
    r.add_strip(Strip(4, 5, 5, "N2"))  # so P3 has a strip; still overlaps jumper end
    res = validate(BOARD, [*inst, stray], nets2, r)
    assert "pin_jumper" in codes(res)


def test_jumper_jumper_overlap():
    inst, nets, r = valid_layout()
    r.add_jumper(Jumper(5, 4, 8, "N1"))  # identical column/rows as existing jumper
    assert "jumper_jumper" in codes(validate(BOARD, inst, nets, r))


# --- Rule 5: cross-net conductive collision -----------------------------------------


def test_cross_net_pin_on_foreign_strip():
    p1 = ComponentInstance("P1", PTYPE, origin=(3, 4))
    p2 = ComponentInstance("P2", PTYPE, origin=(5, 4))  # different net, same row/point-range
    nets = [Net("A", frozenset({("P1", "1")})), Net("B", frozenset({("P2", "1")}))]
    r = Routing()
    r.add_strip(Strip(4, 3, 6, "A"))  # net A strip covers x=5 where P2 (net B) sits
    r.add_strip(Strip(4, 5, 5, "B"))  # P2's own strip too (but overlaps A -> also same_row_gap)
    res = validate(BOARD, [p1, p2], nets, r)
    assert "cross_net" in codes(res)


# --- Rules 6/7/8: connectivity ------------------------------------------------------


def test_pin_not_on_strip():
    p1 = ComponentInstance("P1", PTYPE, origin=(3, 4))
    net = Net("N1", frozenset({("P1", "1")}))
    res = validate(BOARD, [p1], [net], Routing())  # no strips at all
    assert "pin_not_on_strip" in codes(res)


def test_dangling_jumper():
    inst, nets, r = valid_layout()
    # extend a jumper endpoint off its strip: jumper from row4 to row 20 (no strip at row 20)
    r.jumpers["N1"][0] = Jumper(5, 4, 20, "N1")
    assert "dangling_jumper" in codes(validate(BOARD, inst, nets, r))


def test_not_connected():
    p1 = ComponentInstance("P1", PTYPE, origin=(3, 4))
    p2 = ComponentInstance("P2", PTYPE, origin=(3, 8))
    net = Net("N1", frozenset({("P1", "1"), ("P2", "1")}))
    r = Routing()
    r.add_strip(Strip(4, 3, 3, "N1"))  # each pin on its own strip, no jumper joining them
    r.add_strip(Strip(8, 3, 3, "N1"))
    res = validate(BOARD, [p1, p2], [net], r)
    assert "not_connected" in codes(res)


# --- Rule 9: cut not on pin/endpoint ------------------------------------------------


def test_cut_on_pin():
    # Strip [4,5] on row 4 has an edge cut at (3,4); put a foreign pin there.
    p1 = ComponentInstance("P1", PTYPE, origin=(4, 4))
    p2 = ComponentInstance("P2", PTYPE, origin=(3, 4))
    nets = [Net("A", frozenset({("P1", "1")})), Net("B", frozenset({("P2", "1")}))]
    r = Routing()
    r.add_strip(Strip(4, 4, 5, "A"))  # edge cut at (3,4) and (6,4)
    r.add_strip(Strip(4, 3, 3, "B"))  # P2's strip; but (3,4) is a cut of A's strip
    res = validate(BOARD, [p1, p2], nets, r)
    assert "cut_on_pin" in codes(res)


# --- §3.2 permitted overlaps --------------------------------------------------------


def test_strip_through_keepout_permitted():
    body = ComponentInstance("B", ComponentType("BOX", keepouts=(Rect.of(0, 0, 4, 0),)), origin=(3, 4))
    p1 = ComponentInstance("P1", PTYPE, origin=(3, 4))
    net = Net("N1", frozenset({("P1", "1")}))
    r = Routing()
    r.add_strip(Strip(4, 3, 7, "N1"))  # runs through the keep-out row
    res = validate(BOARD, [body, p1], [net], r)
    # pin B has no pins; strip crossing keep-out is allowed. P1 pin is inside its OWN... no,
    # B's keepout at (3,4)..(7,4) overlaps P1 pin at (3,4) -> pin_keepout expected, but
    # strip_keepout must NOT be a violation code.
    assert "strip_keepout" not in codes(res)


def test_jumper_arc_over_foreign_strip_permitted():
    # Net A jumper arcs over a net B strip; conductive points never meet -> allowed.
    pa1 = ComponentInstance("A1", PTYPE, origin=(3, 4))
    pa2 = ComponentInstance("A2", PTYPE, origin=(3, 10))
    pb1 = ComponentInstance("B1", PTYPE, origin=(3, 7))
    nets = [
        Net("A", frozenset({("A1", "1"), ("A2", "1")})),
        Net("B", frozenset({("B1", "1")})),
    ]
    r = Routing()
    r.add_strip(Strip(4, 3, 5, "A"))  # pin at x=3, jumper endpoint at x=5
    r.add_strip(Strip(10, 3, 5, "A"))
    r.add_jumper(Jumper(5, 4, 10, "A"))  # arc over rows 5..9 at x=5
    r.add_strip(Strip(7, 3, 8, "B"))  # crosses x=5 at row 7 (under the arc)
    res = validate(BOARD, [pa1, pa2, pb1], nets, r)
    assert res.ok, res.summary()
