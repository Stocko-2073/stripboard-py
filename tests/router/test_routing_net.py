"""Per-net router tests (Phase 2a): route single nets, then validate the result."""

from __future__ import annotations

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
from stripboard.router.netgraph import is_connected
from stripboard.router.netlist import internal_tie_pairs, pin_world_positions, resolve
from stripboard.router.occupancy import build_obstacles
from stripboard.router.routing.net_router import route_net
from stripboard.router.validation import validate

BOARD = Board(34, 26)
PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))


def route_all(board, instances, netlist):
    """Sequentially route every net onto a shared Routing (no rip-up yet)."""
    resolved = resolve(instances, netlist)
    pin_pos = pin_world_positions(instances)
    internal = internal_tie_pairs(instances)
    routing = Routing()
    for net in resolved.nets:
        obstacles = build_obstacles(instances, routing, resolved.pin_to_net, net.id)
        result = route_net(board, net, pin_pos, internal, obstacles)
        assert result is not None, f"net {net.id} failed to route"
        strips, jumpers = result
        for s in strips:
            routing.add_strip(s)
        for j in jumpers:
            routing.add_jumper(j)
    return resolved, routing


def test_single_pin_gets_a_strip():
    p1 = ComponentInstance("P1", PIN, origin=(5, 5))
    inst = [p1]
    nets = [Net("N", frozenset({("P1", "1")}))]
    _, routing = route_all(BOARD, inst, nets)
    assert len(routing.all_strips()) == 1
    assert routing.all_jumpers() == []
    assert validate(BOARD, inst, nets, routing).ok


def test_two_pins_same_row_one_strip_no_jumper():
    inst = [ComponentInstance("P1", PIN, origin=(2, 4)), ComponentInstance("P2", PIN, origin=(6, 4))]
    nets = [Net("N", frozenset({("P1", "1"), ("P2", "1")}))]
    _, routing = route_all(BOARD, inst, nets)
    assert len(routing.strips_of("N")) == 1
    assert routing.jumpers_of("N") == []
    res = validate(BOARD, inst, nets, routing)
    assert res.ok, res.summary()


def test_two_pins_two_rows_uses_one_jumper():
    inst = [ComponentInstance("P1", PIN, origin=(3, 4)), ComponentInstance("P2", PIN, origin=(3, 10))]
    nets = [Net("N", frozenset({("P1", "1"), ("P2", "1")}))]
    _, routing = route_all(BOARD, inst, nets)
    assert len(routing.jumpers_of("N")) == 1
    res = validate(BOARD, inst, nets, routing)
    assert res.ok, res.summary()
    pins = sorted({("P1", "1"), ("P2", "1")})
    assert is_connected(pins, pin_world_positions(inst), routing.strips_of("N"), routing.jumpers_of("N"), [])


def test_three_pins_three_rows_connected():
    inst = [
        ComponentInstance("P1", PIN, origin=(2, 4)),
        ComponentInstance("P2", PIN, origin=(8, 9)),
        ComponentInstance("P3", PIN, origin=(5, 14)),
    ]
    nets = [Net("N", frozenset({("P1", "1"), ("P2", "1"), ("P3", "1")}))]
    _, routing = route_all(BOARD, inst, nets)
    res = validate(BOARD, inst, nets, routing)
    assert res.ok, res.summary()
    assert len(routing.jumpers_of("N")) == 2  # tree over 3 rows -> 2 jumpers


def test_multiple_independent_nets_all_valid():
    inst = [
        ComponentInstance("A1", PIN, origin=(2, 2)),
        ComponentInstance("A2", PIN, origin=(2, 8)),
        ComponentInstance("B1", PIN, origin=(20, 3)),
        ComponentInstance("B2", PIN, origin=(24, 3)),
    ]
    nets = [
        Net("A", frozenset({("A1", "1"), ("A2", "1")})),
        Net("B", frozenset({("B1", "1"), ("B2", "1")})),
    ]
    _, routing = route_all(BOARD, inst, nets)
    res = validate(BOARD, inst, nets, routing)
    assert res.ok, res.summary()


def test_router_routes_around_foreign_pin_under_arc():
    # A two-row net whose natural column is blocked by a foreign pin in an intermediate row.
    a1 = ComponentInstance("A1", PIN, origin=(5, 4))
    a2 = ComponentInstance("A2", PIN, origin=(5, 12))
    blocker = ComponentInstance("B1", PIN, origin=(6, 8))  # sits where an x=6 arc would pass
    inst = [a1, a2, blocker]
    nets = [
        Net("A", frozenset({("A1", "1"), ("A2", "1")})),
        Net("B", frozenset({("B1", "1")})),
    ]
    _, routing = route_all(BOARD, inst, nets)
    res = validate(BOARD, inst, nets, routing)
    assert res.ok, res.summary()
    # jumper must not be in column 6 (arc would cross the blocker pin at (6,8))
    assert all(j.x != 6 for j in routing.jumpers_of("A"))


def test_same_column_nested_nets_route_full_width():
    # Six 2-pin nets, all pins in column 5, with nested row spans so every jumper arc overlaps
    # -> each net needs a distinct jumper column. The old +/-2 window around the pin column
    # offered only four usable columns (3,4,6,7) and left two nets unroutable; the full-width
    # search places jumpers wherever the board is free (SPEC 2.2 puts no proximity limit on a
    # jumper column). Regression for audit Finding 1.
    board = Board(40, 26)
    inst, nets = [], []
    for i in range(6):
        ya, yb = 5 + i, 20 - i  # nested spans, all pins in column x=5
        inst += [
            ComponentInstance(f"N{i}a", PIN, origin=(5, ya)),
            ComponentInstance(f"N{i}b", PIN, origin=(5, yb)),
        ]
        nets.append(Net(f"N{i}", frozenset({(f"N{i}a", "1"), (f"N{i}b", "1")})))
    _, routing = route_all(board, inst, nets)  # asserts every net routed
    res = validate(board, inst, nets, routing)
    assert res.ok, res.summary()
    assert len({j.x for j in routing.all_jumpers()}) == 6  # a distinct column per net
    # at least one jumper lands outside the old +/-2 window -- exactly what the fix enables
    assert any(abs(j.x - 5) > 2 for j in routing.all_jumpers())


# --- Steiner-row detour: boxed-in net that only routes through an empty row --------------------

# 555 DIP footprint (no body keep-out, matching the top-level sb.dip). Opposite pins share a
# row: left column at local x=0, right column at local x=3. Placed at origin (18,14):
#   TRG->(18,15)  THR->(21,16), boxed in by OUT(18,16) DIS(21,15) RES(18,17) CTL(21,17)
#   GND(18,14) VCC(21,14).
_DIP555 = ComponentType(
    "555",
    pins=(
        PinDef("GND", (0, 0)), PinDef("TRG", (0, 1)), PinDef("OUT", (0, 2)), PinDef("RES", (0, 3)),
        PinDef("VCC", (3, 0)), PinDef("DIS", (3, 1)), PinDef("THR", (3, 2)), PinDef("CTL", (3, 3)),
    ),
)


def test_boxed_corner_net_routes_via_steiner_row():
    # TRG(18,15) and THR(21,16) are diagonally adjacent and hemmed in on all sides. No single
    # jumper is legal -- cols 19/20 each force a strip whose edge-cut lands on a neighbor pin,
    # and any wider column makes a strip cover a foreign pin. The router must detour through an
    # empty row (13 or 18), spending a second jumper.
    inst = [ComponentInstance("U1", _DIP555, origin=(18, 14))]
    nets = [Net("N", frozenset({("U1", "TRG"), ("U1", "THR")}))]
    _, routing = route_all(BOARD, inst, nets)
    assert len(routing.jumpers_of("N")) == 2  # 2 pin rows + 1 Steiner row -> 2 jumpers
    res = validate(BOARD, inst, nets, routing)
    assert res.ok, res.summary()
    pins = sorted({("U1", "TRG"), ("U1", "THR")})
    assert is_connected(
        pins, pin_world_positions(inst), routing.strips_of("N"), routing.jumpers_of("N"), []
    )


def test_boxed_corner_detour_is_legal_when_constructed_by_hand():
    # Independent proof that a legal 2-jumper detour EXISTS, so a router reporting "infeasible"
    # is wrong. Build the exact route by hand ("down col 19 to spare row 18, across, up col 20")
    # plus a trivial strip per foreign pin, and run the independent validator.
    inst = [ComponentInstance("U1", _DIP555, origin=(18, 14))]
    nets = [Net("N", frozenset({("U1", "TRG"), ("U1", "THR")}))]
    resolved = resolve(inst, nets)
    r = Routing()
    r.add_strip(Strip(15, 18, 19, "N"))
    r.add_strip(Strip(18, 19, 20, "N"))
    r.add_strip(Strip(16, 20, 21, "N"))
    r.add_jumper(Jumper(19, 15, 18, "N"))
    r.add_jumper(Jumper(20, 16, 18, "N"))
    # each foreign pin needs a strip of its own (synthesized) net to satisfy validator rule 6
    for ref, (x, y) in pin_world_positions(inst).items():
        nid = resolved.pin_to_net[ref]
        if nid != "N":
            r.add_strip(Strip(y, x, x, nid))
    res = validate(BOARD, inst, nets, r)
    assert res.ok, res.summary()
