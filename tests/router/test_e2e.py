"""End-to-end pipeline tests: route() -> independent validator -> cost recompute."""

from __future__ import annotations

import pytest

from stripboard.router import (
    Board,
    ComponentInstance,
    ComponentType,
    Net,
    PinDef,
    Rect,
    RouteOptions,
    RouteStatus,
    RoutingInfeasibleError,
    compute_cost,
    route,
    validate,
)

BOARD = Board(34, 26)
PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def dip8():
    # A DIP-8-ish part: pins down two columns, body keep-out between them.
    pins = tuple(PinDef(f"{i+1}", (0, i)) for i in range(4)) + tuple(
        PinDef(f"{i+5}", (3, 3 - i)) for i in range(4)
    )
    return ComponentType("DIP8", pins=pins, keepouts=(Rect.of(1, 0, 2, 3),))


def test_route_two_pin_net_feasible_and_valid():
    inst = [ComponentInstance("P1", PIN, origin=(3, 4), locked=True),
            ComponentInstance("P2", PIN, origin=(10, 12), locked=True)]
    nets = [Net("N", frozenset({("P1", "1"), ("P2", "1")}))]
    result = route(BOARD, inst, nets, seed=0)
    assert result.status is RouteStatus.FEASIBLE
    assert result.ok
    # (a) independent validator agrees
    placed_inst = [
        ComponentInstance(p.instance_id, PIN, origin=p.origin, flipped=p.flipped)
        for p in result.placements
    ]
    assert validate(BOARD, placed_inst, nets, result.routing).ok
    # (b) reported cost == fresh recompute
    fresh = compute_cost(BOARD, placed_inst, nets, result.routing)
    assert fresh.total == result.cost.total


def test_boxed_corner_dip_net_routes_end_to_end():
    # A 555-style DIP with NO body keep-out (matches the top-level sb.dip footprint). The net
    # joining diagonally-adjacent TRG(18,15)/THR(21,16) is boxed in by neighbor pins and only
    # routes by detouring through an empty row. Exercises the full pipeline incl. minimize_cuts.
    dip = ComponentType(
        "555",
        pins=(
            PinDef("GND", (0, 0)), PinDef("TRG", (0, 1)), PinDef("OUT", (0, 2)), PinDef("RES", (0, 3)),
            PinDef("VCC", (3, 0)), PinDef("DIS", (3, 1)), PinDef("THR", (3, 2)), PinDef("CTL", (3, 3)),
        ),
    )
    inst = [ComponentInstance("U1", dip, origin=(18, 14), locked=True)]
    nets = [Net("N", frozenset({("U1", "TRG"), ("U1", "THR")}))]
    result = route(BOARD, inst, nets, seed=0)
    assert result.status is RouteStatus.FEASIBLE, [
        (ns.net_id, ns.routed, ns.reason) for ns in result.net_status
    ]
    assert result.ok
    placed_inst = [
        ComponentInstance(p.instance_id, dip, origin=p.origin, flipped=p.flipped)
        for p in result.placements
    ]
    assert validate(BOARD, placed_inst, nets, result.routing).ok


def test_route_with_placement_and_component():
    d = dip8()
    inst = [
        ComponentInstance("U1", d, origin=(5, 5), locked=True),
        ComponentInstance("R1", PIN, origin=(1, 1)),  # unlocked, will be placed
        ComponentInstance("R2", PIN, origin=(20, 20)),
    ]
    nets = [
        Net("A", frozenset({("U1", "1"), ("R1", "1")})),
        Net("B", frozenset({("U1", "8"), ("R2", "1")})),
    ]
    result = route(BOARD, inst, nets, seed=0)
    assert result.status is RouteStatus.FEASIBLE, result.validation.summary()
    assert result.ok


def test_determinism_same_seed_identical_result():
    inst = [ComponentInstance("P1", PIN, origin=(2, 2)),
            ComponentInstance("P2", PIN, origin=(2, 9)),
            ComponentInstance("P3", PIN, origin=(9, 2)),
            ComponentInstance("P4", PIN, origin=(9, 9))]
    nets = [Net("A", frozenset({("P1", "1"), ("P2", "1")})),
            Net("B", frozenset({("P3", "1"), ("P4", "1")}))]
    from stripboard.router.serialization import to_dict

    r1 = route(BOARD, inst, nets, seed=5)
    r2 = route(BOARD, inst, nets, seed=5)
    assert to_dict(r1) == to_dict(r2)


def test_ground_net_end_to_end():
    inst = []
    refs = set()
    for k in range(10):
        y = 2 + k * 2
        inst.append(ComponentInstance(f"G{k}", PIN, origin=(3, y), locked=True))
        refs.add((f"G{k}", "1"))
    nets = [Net("GND", frozenset(refs))]
    result = route(BOARD, inst, nets, seed=0)
    assert result.status is RouteStatus.FEASIBLE
    assert result.ok


def test_two_pin_jumper_minimizes_weighted_diameter():
    # Findings 4 & 5: the per-net search must minimize the weighted electrical diameter, not a
    # pre-extension cut count (which Phase 2c erases anyway) and it must honour net.weight. A
    # jumper between the pins gives diameter 7 (total cost 17); the old router hugged column 1
    # (diameter 9, cost 19) chasing pre-extension cuts, and ignored the weight (cost 100 rather
    # than 80 at weight 10). Cost is asserted both as reported and as an independent recompute.
    inst = [
        ComponentInstance("P", PIN, origin=(2, 4), locked=True),
        ComponentInstance("Q", PIN, origin=(8, 5), locked=True),
    ]
    for weight, expected in ((1.0, 17.0), (10.0, 80.0)):
        nets = [Net("W", frozenset({("P", "1"), ("Q", "1")}), weight=weight)]
        result = route(BOARD, inst, nets, seed=0)
        assert result.ok
        assert result.cost.total == expected, (weight, result.cost.total)
        placed = [
            ComponentInstance(p.instance_id, PIN, origin=p.origin, flipped=p.flipped)
            for p in result.placements
        ]
        assert validate(BOARD, placed, nets, result.routing).ok
        assert compute_cost(BOARD, placed, nets, result.routing).total == expected


def test_on_infeasible_raise():
    # On a 1-column board a 2-row net is unroutable: the only jumper column (1) would place
    # endpoints on the pins themselves. Routing (not placement) is infeasible.
    narrow = Board(1, 5)
    inst = [ComponentInstance("P1", PIN, origin=(1, 1), locked=True),
            ComponentInstance("P2", PIN, origin=(1, 5), locked=True)]
    nets = [Net("A", frozenset({("P1", "1"), ("P2", "1")}))]
    # partial mode returns a non-ok result; raise mode raises
    res = route(narrow, inst, nets, seed=0, options=RouteOptions(on_infeasible="partial"))
    assert not res.ok
    assert res.status is not RouteStatus.FEASIBLE
    with pytest.raises(RoutingInfeasibleError):
        route(narrow, inst, nets, seed=0, options=RouteOptions(on_infeasible="raise"))
