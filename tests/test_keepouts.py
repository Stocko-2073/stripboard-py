"""Keep-out rectangles: the board area a part's body makes unusable for routing.

These are local rects `(x0, y0, x1, y1)` relative to the part origin. They reach the
solver as `ComponentType` keep-outs, so an error here shows up as a router that runs
jumpers underneath a component body.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def wide_board(make_board):
    return make_board(24, "Z", page=(40, 40))


def test_resistor_body_is_a_keepout_between_its_pins(wide_board):
    """An axial resistor lying flat blocks the holes it spans, but not its own pads."""
    assert wide_board.resist(18, "R", "330", l=8).keepouts == ((0, 1, 0, 7),)


def test_resistor_keepout_tracks_its_length(wide_board):
    assert wide_board.resist(10, "B", "1K", l=4).keepouts == ((0, 1, 0, 3),)


def test_button_body_overhangs_its_pads(wide_board):
    """A tactile switch's body is wider than its legs, including one row above them."""
    assert wide_board.big_button(13, "L").keepouts == ((1, -1, 4, 3),)


def test_two_pin_parts_have_no_body_keepout(wide_board):
    """Caps, LEDs and diodes stand upright, so they occupy only their own holes."""
    assert wide_board.cap(17, "D").keepouts == ()
    assert wide_board.led(17, "R").keepouts == ()
    assert wide_board.diode(5, "B").keepouts == ()


def test_explicit_keepout_reserves_a_rect_with_no_pins(wide_board):
    ko = wide_board.keepout(3, "C", 2, 2)
    assert ko.pins == {}
    assert ko.keepouts == ((0, 0, 1, 1),)


class TestTerminalShroud:
    """A terminal block's plastic shroud buries the holes on either side of its legs."""

    def test_two_way_block(self, wide_board):
        t = wide_board.terminal(3, "C", 2)
        assert t.keepouts == ((-1, 0, 1, 1),)      # columns 2..4, rows C..D

    def test_every_other_row_with_an_offset_shroud(self, wide_board):
        """mod=2 puts legs on alternate rows; the offset shroud stops one row short."""
        t = wide_board.terminal(8, "F", 12, mod=2, shroud_y_offset=-0.5)
        assert {k: v for k, v in sorted(t.pins.items())}  # sanity: it has pins
        assert t.keepouts == ((-1, 0, 1, 10),)

    def test_keepout_is_clamped_to_the_left_board_edge(self, wide_board):
        assert wide_board.terminal(1, "C", 2).keepouts == ((0, 0, 1, 1),)

    def test_keepout_is_clamped_to_the_right_board_edge(self, make_board):
        board = make_board(18, "Z")
        assert board.terminal(18, "C", 2).keepouts == ((-1, 0, 0, 1),)


@pytest.mark.parametrize(("name", "build", "expected"), [
    ("resist", lambda b: b.resist(18, "R", "330", l=8), [(0, 1, 0, 7)]),
    ("big_button", lambda b: b.big_button(13, "L"), [(1, -1, 4, 3)]),
    ("terminal", lambda b: b.terminal(3, "C", 2), [(-1, 0, 1, 1)]),
])
def test_keepouts_reach_the_router(wide_board, name, build, expected):
    comp = build(wide_board)
    _, instances, _ = wide_board._build_problem()
    inst = next(i for i in instances if i.id == comp.id)
    assert [(r.x0, r.y0, r.x1, r.y1) for r in inst.type.keepouts] == expected
