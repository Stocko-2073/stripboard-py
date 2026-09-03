"""Strip-extent cut-minimization tests (Phase 2c)."""

from __future__ import annotations

from stripboard.router.cuts import physical_cuts
from stripboard.router.model import (
    Board,
    ComponentInstance,
    ComponentType,
    Net,
    PinDef,
    Routing,
    Strip,
)
from stripboard.router.netgraph import net_length
from stripboard.router.netlist import resolve
from stripboard.router.routing.ripup import route_nets
from stripboard.router.routing.strip_extent import minimize_cuts
from stripboard.router.validation import validate

BOARD = Board(34, 26)
PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def test_single_strip_extends_to_full_row_no_cuts():
    r = Routing()
    r.add_strip(Strip(4, 2, 6, "N"))
    assert len(physical_cuts(r.all_strips(), 34, 26)) == 2
    out = minimize_cuts(BOARD, r)
    s = out.strips_of("N")[0]
    assert (s.xa, s.xb) == (1, 34)
    assert len(physical_cuts(out.all_strips(), 34, 26)) == 0


def test_adjacent_strips_share_one_cut():
    r = Routing()
    r.add_strip(Strip(4, 2, 4, "A"))
    r.add_strip(Strip(4, 8, 10, "B"))
    assert len(physical_cuts(r.all_strips(), 34, 26)) == 4
    out = minimize_cuts(BOARD, r)
    cuts = physical_cuts(out.all_strips(), 34, 26)
    assert cuts == {(7, 4)}  # single shared cut in the 1-column gap
    a = next(s for s in out.all_strips() if s.net_id == "A")
    b = next(s for s in out.all_strips() if s.net_id == "B")
    assert (a.xa, a.xb) == (1, 6)
    assert (b.xa, b.xb) == (8, 34)


def test_diameter_unchanged_by_extension():
    pins = [("P1", "1"), ("P2", "1")]
    pos = {("P1", "1"): (2, 4), ("P2", "1"): (6, 4)}
    r = Routing()
    r.add_strip(Strip(4, 2, 6, "N"))
    before = net_length(pins, pos, r.strips_of("N"), [], [])
    out = minimize_cuts(BOARD, r)
    after = net_length(pins, pos, out.strips_of("N"), [], [])
    assert before == after == 4.0


def test_cut_pass_preserves_validity_and_reduces_cuts():
    inst = []
    nets = []
    for k in range(4):
        x = 2 + k * 5
        inst += [ComponentInstance(f"P{k}a", PIN, origin=(x, 3)),
                 ComponentInstance(f"P{k}b", PIN, origin=(x, 12))]
        nets.append(Net(f"N{k}", frozenset({(f"P{k}a", "1"), (f"P{k}b", "1")})))
    resolved = resolve(inst, nets)
    gr = route_nets(BOARD, inst, resolved, seed=0)
    assert not gr.unrouted
    before_cuts = len(physical_cuts(gr.routing.all_strips(), 34, 26))
    out = minimize_cuts(BOARD, gr.routing)
    after_cuts = len(physical_cuts(out.all_strips(), 34, 26))
    assert after_cuts <= before_cuts
    res = validate(BOARD, inst, nets, out)
    assert res.ok, res.summary()
