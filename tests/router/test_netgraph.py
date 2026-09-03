"""Net length (electrical diameter) and connectivity tests (SPEC section 4.3/4.2)."""

from __future__ import annotations

import math

from stripboard.router.model import Jumper, Strip
from stripboard.router.netgraph import is_connected, net_length


def test_single_pin_length_zero():
    assert net_length([("P1", "1")], {("P1", "1"): (3, 4)}, [], [], []) == 0.0


def test_two_pins_same_strip_horizontal_distance():
    pins = [("P1", "1"), ("P2", "1")]
    pos = {("P1", "1"): (3, 4), ("P2", "1"): (8, 4)}
    strips = [Strip(4, 3, 8, "N")]
    assert net_length(pins, pos, strips, [], []) == 5.0  # |8-3|


def test_two_pins_via_jumper():
    # pins on rows 4 and 10 at x=3; strips reach x=5; jumper x=5 spans vlength 6.
    pins = [("P1", "1"), ("P2", "1")]
    pos = {("P1", "1"): (3, 4), ("P2", "1"): (3, 10)}
    strips = [Strip(4, 3, 5, "N"), Strip(10, 3, 5, "N")]
    jumpers = [Jumper(5, 4, 10, "N")]
    # path: (3,4)->(5,4) = 2 on strip; jumper = 6; (5,10)->(3,10) = 2 on strip; total 10
    assert net_length(pins, pos, strips, jumpers, []) == 10.0


def test_internal_connection_distance_zero():
    # Two pins internally tied -> distance 0 even without a strip joining them.
    pins = [("U1", "A"), ("U1", "B")]
    pos = {("U1", "A"): (3, 4), ("U1", "B"): (9, 12)}
    strips = [Strip(4, 3, 3, "N"), Strip(12, 9, 9, "N")]
    pairs = [(("U1", "A"), ("U1", "B"))]
    assert net_length(pins, pos, strips, [], pairs) == 0.0


def test_disconnected_is_inf_and_not_connected():
    pins = [("P1", "1"), ("P2", "1")]
    pos = {("P1", "1"): (3, 4), ("P2", "1"): (3, 10)}
    strips = [Strip(4, 3, 3, "N"), Strip(10, 3, 3, "N")]  # no jumper joining rows
    assert math.isinf(net_length(pins, pos, strips, [], []))
    assert not is_connected(pins, pos, strips, [], [])


def test_corollary_extend_strip_past_pins_keeps_length():
    # SPEC section 4.3 corollary: dead-end copper doesn't change net length.
    pins = [("P1", "1"), ("P2", "1")]
    pos = {("P1", "1"): (3, 4), ("P2", "1"): (8, 4)}
    short = [Strip(4, 3, 8, "N")]
    long = [Strip(4, 1, 20, "N")]  # extends well past the pins
    assert net_length(pins, pos, short, [], []) == net_length(pins, pos, long, [], [])
