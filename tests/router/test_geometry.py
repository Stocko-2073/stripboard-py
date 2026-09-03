"""Geometry + entity tests, drawn straight from SPEC section 5 examples."""

from __future__ import annotations

import pytest

from stripboard.router.cuts import physical_cuts
from stripboard.router.geometry import Rect, flip_point, manhattan, parse_row
from stripboard.router.model import Jumper, Strip

W, H = 34, 26


def test_manhattan():
    assert manhattan((1, 1), (4, 5)) == 7
    assert manhattan((3, 3), (3, 3)) == 0


# --- Strip cuts (SPEC section 5 examples) ---------------------------------------------


def test_strip_cuts_interior():
    assert Strip(9, 3, 5, "n").edge_cuts(W, H) == {(2, 9), (6, 9)}


def test_strip_cuts_left_edge_offboard():
    # strip(1:19, 9) -> only (20,9); (0,9) is off board
    assert Strip(9, 1, 19, "n").edge_cuts(W, H) == {(20, 9)}


def test_strip_cuts_full_width_none():
    # strip(1:34, 9) on a 34-wide board -> no cuts (both off board)
    assert Strip(9, 1, 34, "n").edge_cuts(W, H) == set()


def test_strip_cuts_single_point():
    assert Strip(9, 5, 5, "n").edge_cuts(W, H) == {(4, 9), (6, 9)}


def test_strip_length_and_points():
    s = Strip(9, 3, 5, "n")
    assert s.length() == 2
    assert s.points_count() == 3
    assert list(s.points()) == [(3, 9), (4, 9), (5, 9)]
    lone = Strip(9, 5, 5, "n")
    assert lone.length() == 0
    assert lone.points_count() == 1


def test_strip_requires_ordered():
    with pytest.raises(ValueError):
        Strip(9, 6, 3, "n")


# --- physical cut collapse -----------------------------------------------------------


def test_physical_cuts_collapse_shared():
    # Two same-row strips separated by one empty column share the gap cut (counts once).
    a = Strip(4, 1, 3, "n1")  # cut at (4,4)
    b = Strip(4, 5, 6, "n2")  # cut at (4,4) and (7,4)
    cuts = physical_cuts([a, b], W, H)
    assert (4, 4) in cuts
    assert cuts == {(4, 4), (7, 4)}
    assert len(cuts) == 2


def test_physical_cuts_order_invariant():
    a = Strip(4, 1, 3, "n1")
    b = Strip(4, 5, 6, "n2")
    assert physical_cuts([a, b], W, H) == physical_cuts([b, a], W, H)


# --- Jumper keep-out (SPEC section 2.2) ----------------------------------------------


def test_jumper_keepout_vlength1_empty():
    j = Jumper(7, 4, 5, "n")
    assert j.vlength() == 1
    assert j.keepout() == set()
    assert j.endpoints() == ((7, 4), (7, 5))


def test_jumper_keepout_interior_column():
    j = Jumper(7, 4, 8, "n")
    assert j.vlength() == 4
    assert j.keepout() == {(7, 5), (7, 6), (7, 7)}


def test_jumper_requires_ordered():
    with pytest.raises(ValueError):
        Jumper(7, 5, 5, "n")


# --- 180-degree flip is an involution (SPEC section 2.3) -----------------------------


def test_flip_point_involution():
    for p in [(0, 0), (3, -2), (-5, 7), (1, 1)]:
        assert flip_point(flip_point(p)) == p


def test_flip_rect_mapping_and_involution():
    r = Rect.of(2, 3, 5, 9)
    assert r.flip() == Rect(-5, -9, -2, -3)  # [x0,x1]x[y0,y1] -> [-x1,-x0]x[-y1,-y0]
    assert r.flip().flip() == r


def test_rect_of_normalizes():
    assert Rect.of(5, 9, 2, 3) == Rect(2, 3, 5, 9)


def test_rect_rejects_reversed_direct_construction():
    with pytest.raises(ValueError):
        Rect(5, 3, 2, 9)


def test_rect_points():
    assert set(Rect(1, 1, 2, 2).points()) == {(1, 1), (2, 1), (1, 2), (2, 2)}


# --- row letter alias ----------------------------------------------------------------


def test_parse_row_letters_and_ints():
    assert parse_row("A") == 1
    assert parse_row("Z") == 26
    assert parse_row("m") == 13
    assert parse_row(5) == 5
    assert parse_row("14") == 14
    with pytest.raises(ValueError):
        parse_row("??")
