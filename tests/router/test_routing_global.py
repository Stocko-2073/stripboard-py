"""Global rip-up/reroute tests (Phase 2b)."""

from __future__ import annotations

from stripboard.router.model import Board, ComponentInstance, ComponentType, Net, PinDef
from stripboard.router.netlist import resolve
from stripboard.router.routing.ripup import route_nets
from stripboard.router.validation import validate

BOARD = Board(34, 26)
PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def _inst(*specs):
    return [ComponentInstance(i, PIN, origin=o) for (i, o) in specs]


def test_two_nets_route_and_validate():
    inst = _inst(("A1", (2, 2)), ("A2", (2, 10)), ("B1", (5, 2)), ("B2", (5, 10)))
    nets = [
        Net("A", frozenset({("A1", "1"), ("A2", "1")})),
        Net("B", frozenset({("B1", "1"), ("B2", "1")})),
    ]
    resolved = resolve(inst, nets)
    result = route_nets(BOARD, inst, resolved, seed=0)
    assert not result.unrouted, result.unrouted
    assert validate(BOARD, inst, nets, result.routing).ok


def test_many_small_nets_all_route():
    inst = []
    nets = []
    for k in range(6):
        x = 2 + k * 4
        inst += _inst((f"P{k}a", (x, 3)), (f"P{k}b", (x, 12)))
        nets.append(Net(f"N{k}", frozenset({(f"P{k}a", "1"), (f"P{k}b", "1")})))
    resolved = resolve(inst, nets)
    result = route_nets(BOARD, inst, resolved, seed=1)
    assert not result.unrouted, result.unrouted
    res = validate(BOARD, inst, nets, result.routing)
    assert res.ok, res.summary()


def test_ground_net_10_pins():
    # A larger net spanning many rows -- the "ground net" case.
    inst = []
    refs = set()
    for k in range(10):
        y = 2 + k * 2
        inst += _inst((f"G{k}", (3, y)),)
        refs.add((f"G{k}", "1"))
    nets = [Net("GND", frozenset(refs))]
    resolved = resolve(inst, nets)
    result = route_nets(BOARD, inst, resolved, seed=0)
    assert not result.unrouted, result.unrouted
    res = validate(BOARD, inst, nets, result.routing)
    assert res.ok, res.summary()


def test_determinism_same_seed():
    inst = _inst(("A1", (2, 2)), ("A2", (2, 10)), ("B1", (5, 2)), ("B2", (5, 10)))
    nets = [
        Net("A", frozenset({("A1", "1"), ("A2", "1")})),
        Net("B", frozenset({("B1", "1"), ("B2", "1")})),
    ]
    resolved = resolve(inst, nets)
    r1 = route_nets(BOARD, inst, resolved, seed=7)
    r2 = route_nets(BOARD, inst, resolved, seed=7)

    def key(r):
        return (
            sorted((s.net_id, s.y, s.xa, s.xb) for s in r.routing.all_strips()),
            sorted((j.net_id, j.x, j.ya, j.yb) for j in r.routing.all_jumpers()),
        )

    assert key(r1) == key(r2)


def test_confined_high_fanout_net_routes():
    # An 8-pin net over 6 rows squeezed against obstacle pins in column 11: a strip whose right
    # cut would land on column 11 is invalid, so the jumper columns must be coordinated to keep
    # every strip's cut clear. The old chain-only topology + greedy, no-backtracking column
    # search gave up here (partial); the branch-and-bound search finds the coordinated
    # assignment. Regression for audit Findings 2 & 3 (the high-fan-out field bug).
    gnd = [(9, 3), (8, 3), (9, 6), (9, 9), (9, 12), (9, 15), (9, 18), (8, 18)]
    inst, refs = [], set()
    for k, (x, y) in enumerate(gnd):
        inst.append(ComponentInstance(f"G{k}", PIN, origin=(x, y)))
        refs.add((f"G{k}", "1"))
    nets = [Net("GND", frozenset(refs))]
    for k, y in enumerate((3, 6, 9, 12, 15, 18)):
        inst.append(ComponentInstance(f"O{k}", PIN, origin=(11, y)))
        nets.append(Net(f"O{k}", frozenset({(f"O{k}", "1")})))
    result = route_nets(BOARD, inst, resolve(inst, nets), seed=0)
    assert not result.unrouted, result.unrouted
    res = validate(BOARD, inst, nets, result.routing)
    assert res.ok, res.summary()
