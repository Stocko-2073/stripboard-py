"""Cost breakdown tests (SPEC section 7)."""

from __future__ import annotations

from stripboard.router.cost import compute_cost
from stripboard.router.model import (
    Board,
    ComponentInstance,
    ComponentType,
    Jumper,
    Net,
    PinDef,
    Routing,
    Strip,
    Weights,
)
from stripboard.router.validation import validate

BOARD = Board(34, 26)
PTYPE = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def _layout():
    p1 = ComponentInstance("P1", PTYPE, origin=(3, 4))
    p2 = ComponentInstance("P2", PTYPE, origin=(3, 10))
    net = Net("N1", frozenset({("P1", "1"), ("P2", "1")}))
    r = Routing()
    r.add_strip(Strip(4, 3, 5, "N1"))
    r.add_strip(Strip(10, 3, 5, "N1"))
    r.add_jumper(Jumper(5, 4, 10, "N1"))
    return [p1, p2], [net], r


def test_cost_breakdown_matches_hand_calc():
    inst, nets, r = _layout()
    cb = compute_cost(BOARD, inst, nets, r)
    # net length: (3,4)->(5,4)=2 + jumper 6 + (5,10)->(3,10)=2 = 10
    assert cb.weighted_net_length == 10.0
    assert cb.num_jumpers == 1
    # cuts: row4 [3,5] -> (2,4),(6,4); row10 [3,5] -> (2,10),(6,10) -> 4 distinct
    assert cb.num_cuts == 4
    # total = 1*10 + 10*1 + 3*4 = 32
    assert cb.total == 32.0


def test_shared_cut_counts_once():
    p1 = ComponentInstance("P1", PTYPE, origin=(1, 4))
    p2 = ComponentInstance("P2", PTYPE, origin=(6, 4))
    nets = [Net("A", frozenset({("P1", "1")})), Net("B", frozenset({("P2", "1")}))]
    r = Routing()
    r.add_strip(Strip(4, 1, 3, "A"))  # cut at (4,4)
    r.add_strip(Strip(4, 5, 6, "B"))  # cut at (4,4) shared, and (7,4)
    cb = compute_cost(BOARD, [p1, p2], nets, r)
    assert cb.num_cuts == 2  # (4,4) counted once + (7,4)


def test_custom_weights_override():
    inst, nets, r = _layout()
    cb = compute_cost(BOARD, inst, nets, r, weights=Weights(w_len=0, w_jmp=1, w_cut=0))
    assert cb.total == 1.0  # only the single jumper counts


def test_reported_cost_matches_fresh_recompute():
    inst, nets, r = _layout()
    a = compute_cost(BOARD, inst, nets, r)
    b = compute_cost(BOARD, inst, nets, r)
    assert a.total == b.total
    assert validate(BOARD, inst, nets, r).ok
