"""Phase 1 placement tests (SPEC section 7)."""

from __future__ import annotations

import pytest

from stripboard.router.geometry import Rect
from stripboard.router.model import Board, ComponentInstance, ComponentType, Net, PinDef
from stripboard.router.netlist import resolve
from stripboard.router.placement import (
    PlacementError,
    PlacementOptions,
    congestion_field,
    congestion_penalty,
    hpwl,
    is_legal,
    place,
    place_candidates,
)

PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))
BOARD = Board(8, 6)  # small board; w_x=1, w_y=5


def anchors_and_free(free_start):
    a = ComponentInstance("A", PIN, origin=(1, 1), locked=True)
    b = ComponentInstance("B", PIN, origin=(7, 1), locked=True)
    u = ComponentInstance("U", PIN, origin=free_start, locked=False)
    net = [Net("N", frozenset({("A", "1"), ("B", "1"), ("U", "1")}))]
    return [a, b, u], resolve([a, b, u], net)


def test_place_minimizes_hpwl():
    inst, resolved = anchors_and_free((4, 5))
    placed = place(BOARD, inst, resolved, seed=0)
    assert is_legal(BOARD, placed)
    # optimal: U on row 1 within [1,7] -> xspan 6, yspan 0 -> 1*6 + 5*0 = 6
    assert hpwl(placed, resolved, BOARD.weights) == 6.0


def test_brute_force_and_sa_agree():
    inst, resolved = anchors_and_free((4, 5))
    brute = place(BOARD, inst, resolved, seed=0)
    sa = place(BOARD, inst, resolved, seed=0, options=PlacementOptions(brute_force_budget=0))
    assert hpwl(brute, resolved, BOARD.weights) == hpwl(sa, resolved, BOARD.weights) == 6.0


def test_placement_is_deterministic():
    inst, resolved = anchors_and_free((4, 5))
    opts = PlacementOptions(brute_force_budget=0)
    a = place(BOARD, inst, resolved, seed=42, options=opts)
    b = place(BOARD, inst, resolved, seed=42, options=opts)
    assert [(i.id, i.origin, i.flipped) for i in a] == [(i.id, i.origin, i.flipped) for i in b]


def test_result_never_illegal_with_keepouts():
    # Two unlocked boxes pulled together by a net must not end up overlapping.
    box = ComponentType("BOX", pins=(PinDef("1", (0, 0)),), keepouts=(Rect.of(0, 0, 1, 1),))
    u1 = ComponentInstance("U1", box, origin=(1, 1))
    u2 = ComponentInstance("U2", box, origin=(6, 4))
    net = [Net("N", frozenset({("U1", "1"), ("U2", "1")}))]
    resolved = resolve([u1, u2], net)
    placed = place(BOARD, [u1, u2], resolved, seed=1)
    assert is_legal(BOARD, placed)


def test_is_legal_detects_pin_overlap():
    a = ComponentInstance("A", PIN, origin=(3, 3))
    b = ComponentInstance("B", PIN, origin=(3, 3))
    assert not is_legal(BOARD, [a, b])


def test_infeasible_raises():
    # A component too big to fit on board -> no on-board placement.
    big = ComponentType("BIG", keepouts=(Rect.of(0, 0, 100, 0),))
    u = ComponentInstance("U", big, origin=(1, 1))
    with pytest.raises(PlacementError):
        place(BOARD, [u], resolve([u], []), seed=0)


# --------------------------------------------------------------------------- ranked API


def test_place_candidates_ranked_distinct_and_limited():
    inst, resolved = anchors_and_free((4, 5))
    cands = place_candidates(BOARD, inst, resolved, seed=0, limit=3)
    assert 1 <= len(cands) <= 3
    # PIN has no keep-out, so the placement cost is pure HPWL here: candidates ascend by cost.
    costs = [hpwl(c, resolved, BOARD.weights) for c in cands]
    assert costs == sorted(costs)
    # Each returned placement is a distinct configuration of the unlocked parts.
    keys = [tuple((i.id, i.origin, i.flipped) for i in c if not i.locked) for c in cands]
    assert len(keys) == len(set(keys))
    # The best candidate is exactly what place() returns.
    best = place(BOARD, inst, resolved, seed=0)
    assert keys[0] == tuple((i.id, i.origin, i.flipped) for i in best if not i.locked)


# --------------------------------------------------------------------------- congestion


def test_congestion_field_marks_locked_net_bbox():
    # A net between two locked pins on the same row spreads demand along the row between them.
    a = ComponentInstance("A", PIN, origin=(2, 3), locked=True)
    b = ComponentInstance("B", PIN, origin=(6, 3), locked=True)
    resolved = resolve([a, b], [Net("N", frozenset({("A", "1"), ("B", "1")}))])
    field = congestion_field([a, b], resolved)
    assert field[(2, 3)] == 1.0 and field[(4, 3)] == 1.0 and field[(6, 3)] == 1.0
    assert (4, 2) not in field  # off the anchors' bounding box


def test_congestion_penalty_prices_only_unlocked_keepouts_on_hot_cells():
    a = ComponentInstance("A", PIN, origin=(2, 3), locked=True)
    b = ComponentInstance("B", PIN, origin=(6, 3), locked=True)
    resolved = resolve([a, b], [Net("N", frozenset({("A", "1"), ("B", "1")}))])
    field = congestion_field([a, b], resolved)
    wall = ComponentType("W", pins=(PinDef("1", (0, 0)),), keepouts=(Rect.of(0, 0, 0, 0),))
    on_band = ComponentInstance("W", wall, origin=(4, 3), locked=False)
    off_band = ComponentInstance("W", wall, origin=(4, 1), locked=False)
    assert congestion_penalty([a, b, on_band], field) == 1.0
    assert congestion_penalty([a, b, off_band], field) == 0.0
