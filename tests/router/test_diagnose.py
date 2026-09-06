"""Why a net cannot be routed (diagnostics)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stripboard.router.diagnose import conflict_reason, explain_net, row_conflicts
from stripboard.router.geometry import Rect
from stripboard.router.model import (
    Board,
    ComponentInstance,
    ComponentType,
    Net,
    PinDef,
    Routing,
)
from stripboard.router.netlist import internal_tie_pairs, pin_world_positions, resolve
from stripboard.router.occupancy import build_obstacles
from stripboard.router.routing.net_router import route_net
from stripboard.router.routing.ripup import route_nets

BOARD = Board(34, 26)
PIN = ComponentType("P", pins=(PinDef("1", (0, 0)),))
# A pin-less body, to prove a keep-out does not block a strip the way a pin does.
BODY = ComponentType("B", keepouts=(Rect(0, 0, 0, 0),))


def conflicts_for(instances, netlist, net_id):
    resolved = resolve(instances, netlist)
    return row_conflicts(
        resolved.net(net_id), pin_world_positions(instances), resolved.pin_to_net
    )


# ---- the row-span rule ----------------------------------------------------------------

def test_a_foreign_pin_inside_a_rows_pin_span_is_reported():
    """The row's strip has to span the net's own pins, so it would cover the intruder."""
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("R3", PIN, origin=(5, 14)),
    ]
    nets = [
        Net("GND", frozenset({("G1", "1"), ("G2", "1")})),
        Net("3V3", frozenset({("R3", "1")})),
    ]
    (c,) = conflicts_for(inst, nets, "GND")
    assert c.net_id == "GND"
    assert c.row == 14
    assert c.span == (2, 22)
    assert c.blocker == ("R3", "1")
    assert c.blocker_pos == (5, 14)
    assert c.blocker_net == "3V3"


def test_the_message_names_the_part_the_net_and_the_holes():
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("R3", PIN, origin=(5, 14)),
    ]
    nets = [
        Net("GND", frozenset({("G1", "1"), ("G2", "1")})),
        Net("3V3", frozenset({("R3", "1")})),
    ]
    msg = conflicts_for(inst, nets, "GND")[0].message
    assert "(2,14) and (22,14)" in msg
    assert "R3.1 at (5,14)" in msg
    assert "net 3V3" in msg
    assert "row-14 strip" in msg


def test_a_pin_outside_the_span_is_not_a_conflict():
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("R3", PIN, origin=(25, 14)),
    ]
    nets = [Net("GND", frozenset({("G1", "1"), ("G2", "1")}))]
    assert conflicts_for(inst, nets, "GND") == []


def test_a_pin_clear_of_a_lone_pin_on_its_row_is_not_a_conflict():
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 20)),
        ComponentInstance("R3", PIN, origin=(5, 14)),
    ]
    nets = [Net("GND", frozenset({("G1", "1"), ("G2", "1")}))]
    assert conflicts_for(inst, nets, "GND") == []


def test_a_pin_in_the_next_hole_leaves_the_strip_nowhere_to_cut():
    """The cut has to fall on an empty hole, so touching pins of two nets cannot both
    have a strip -- even where nothing is trapped between them."""
    inst = [
        ComponentInstance("G1", PIN, origin=(5, 3)),
        ComponentInstance("G2", PIN, origin=(5, 9)),
        ComponentInstance("R3", PIN, origin=(6, 3)),
    ]
    nets = [
        Net("GND", frozenset({("G1", "1"), ("G2", "1")})),
        Net("3V3", frozenset({("R3", "1")})),
    ]
    (c,) = conflicts_for(inst, nets, "GND")
    assert c.row == 3
    assert c.span == (5, 5)
    assert c.blocker == ("R3", "1")
    assert "immediately alongside" in c.message
    assert "nowhere to cut clear of it" in c.message


def test_a_pin_two_holes_away_is_far_enough():
    """One empty hole between the two strips is all the cut needs."""
    inst = [
        ComponentInstance("G1", PIN, origin=(5, 3)),
        ComponentInstance("G2", PIN, origin=(5, 9)),
        ComponentInstance("R3", PIN, origin=(7, 3)),
    ]
    nets = [
        Net("GND", frozenset({("G1", "1"), ("G2", "1")})),
        Net("3V3", frozenset({("R3", "1")})),
    ]
    assert conflicts_for(inst, nets, "GND") == []


def test_another_pin_of_the_same_net_is_not_foreign():
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("G3", PIN, origin=(5, 14)),
    ]
    nets = [Net("GND", frozenset({("G1", "1"), ("G2", "1"), ("G3", "1")}))]
    assert conflicts_for(inst, nets, "GND") == []


def test_a_keepout_inside_the_span_is_not_a_conflict():
    """A strip may run under a component body; only a conductive point stops it."""
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("B1", BODY, origin=(5, 14)),
    ]
    nets = [Net("GND", frozenset({("G1", "1"), ("G2", "1")}))]
    assert conflicts_for(inst, nets, "GND") == []


def test_every_trapped_pin_is_reported_and_the_reason_counts_them():
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("R3", PIN, origin=(5, 14)),
        ComponentInstance("R4", PIN, origin=(9, 14)),
    ]
    nets = [Net("GND", frozenset({("G1", "1"), ("G2", "1")}))]
    found = conflicts_for(inst, nets, "GND")
    assert [c.blocker for c in found] == [("R3", "1"), ("R4", "1")]
    assert "1 further pin trapped like this" in conflict_reason(found)


# ---- what the router reports ----------------------------------------------------------

def test_the_router_reports_the_conflict_as_that_nets_reason():
    inst = [
        ComponentInstance("G1", PIN, origin=(2, 14)),
        ComponentInstance("G2", PIN, origin=(22, 14)),
        ComponentInstance("R3", PIN, origin=(5, 14)),
    ]
    nets = [
        Net("GND", frozenset({("G1", "1"), ("G2", "1")})),
        Net("3V3", frozenset({("R3", "1")})),
    ]
    result = route_nets(BOARD, inst, resolve(inst, nets), seed=0)
    assert set(result.unrouted) == {"GND"}
    assert "R3.1 at (5,14)" in result.unrouted["GND"]
    assert "3V3" in result.routed


def test_a_routable_board_reports_no_reasons():
    inst = [ComponentInstance("A1", PIN, origin=(2, 2)),
            ComponentInstance("A2", PIN, origin=(2, 10))]
    nets = [Net("A", frozenset({("A1", "1"), ("A2", "1")}))]
    assert not route_nets(BOARD, inst, resolve(inst, nets), seed=0).unrouted


# ---- what the search was working from -------------------------------------------------

def wall_board():
    """A two-row net with a wall of foreign pins across the only row between them."""
    board = Board(6, 10)
    inst = [ComponentInstance("A1", PIN, origin=(2, 2)),
            ComponentInstance("A2", PIN, origin=(2, 8))]
    nets = [Net("A", frozenset({("A1", "1"), ("A2", "1")}))]
    for c in range(1, 7):
        inst.append(ComponentInstance(f"W{c}", PIN, origin=(c, 5)))
        nets.append(Net(f"W{c}", frozenset({(f"W{c}", "1")})))
    return board, inst, nets


def test_a_routable_net_reports_the_columns_it_could_have_used():
    inst = [ComponentInstance("A1", PIN, origin=(2, 2)),
            ComponentInstance("A2", PIN, origin=(8, 10))]
    nets = [Net("A", frozenset({("A1", "1"), ("A2", "1")}))]
    ex = explain_net(BOARD, inst, nets, "A")
    assert ex.routed
    assert ex.pin_count == 2
    assert [(r.row, r.columns) for r in ex.pins] == [(2, (2,)), (10, (8,))]
    ((pair,)) = ex.pairs
    assert (pair.ya, pair.yb) == (2, 10)
    assert 5 in pair.columns and pair.blockers == ()


def test_a_row_pair_with_nowhere_to_bridge_names_what_holds_each_column():
    board, inst, nets = wall_board()
    ex = explain_net(board, inst, nets, "A")
    assert not ex.routed
    ((pair,)) = ex.pairs
    assert pair.columns == ()
    assert [b.column for b in pair.blockers] == [1, 2, 3, 4, 5, 6]
    wall = {b.column: b for b in pair.blockers if b.comp_id}
    assert wall[3].comp_id == "W3"
    assert wall[3].kind == "pin"
    assert wall[3].point == (3, 5)


def test_a_jumper_may_not_land_on_this_nets_own_pin_either():
    board, inst, nets = wall_board()
    ((pair,)) = explain_net(board, inst, nets, "A").pairs
    own = next(b for b in pair.blockers if b.column == 2)
    assert own.kind == "own pin"
    assert own.label == "own pin"


def test_the_printed_report_says_what_it_was_measured_against():
    board, inst, nets = wall_board()
    alone = str(explain_net(board, inst, nets, "A"))
    assert "against the parts alone" in alone
    assert "rows 2 and 8 cannot be bridged" in alone
    assert "pin W3 at (3, 5)" in alone
    assert "routes here: no" in alone


def one_free_column_board():
    """Two nets that each route alone, but whose only jumper column is the same one.

    Keep-out walls close row 5 in every column but 4, so both nets have to arc there.
    Walls rather than pins, so the obstacles need no routing of their own.
    """
    board = Board(8, 10)
    left = ComponentType("WL", keepouts=(Rect(0, 0, 2, 0),))
    right = ComponentType("WR", keepouts=(Rect(0, 0, 3, 0),))
    inst = [ComponentInstance("A1", PIN, origin=(2, 2)),
            ComponentInstance("A2", PIN, origin=(2, 8)),
            ComponentInstance("B1", PIN, origin=(7, 2)),
            ComponentInstance("B2", PIN, origin=(7, 8)),
            ComponentInstance("WL", left, origin=(1, 5)),
            ComponentInstance("WR", right, origin=(5, 5))]
    nets = [Net("A", frozenset({("A1", "1"), ("A2", "1")})),
            Net("B", frozenset({("B1", "1"), ("B2", "1")}))]
    return board, inst, nets


def test_a_net_can_route_alone_and_still_fail_on_the_finished_board():
    """The case worth separating: the net is fine, another net took its column."""
    board, inst, nets = one_free_column_board()
    for net_id in ("A", "B"):
        alone = explain_net(board, inst, nets, net_id)
        assert alone.routed, net_id
        assert alone.pairs[0].columns == (4,), net_id

    result = route_nets(board, inst, resolve(inst, nets), seed=0)
    (loser,) = sorted(result.unrouted)
    ex = explain_net(board, inst, nets, loser, routing=result.routing)
    assert ex.in_context and not ex.routed
    assert ex.conflicts == (), "nothing is wrong with the placement -- the column was taken"
    assert ex.pairs[0].columns == ()
    assert "against the routed board" in str(ex)


def test_the_report_names_the_net_that_took_the_column():
    board, inst, nets = one_free_column_board()
    result = route_nets(board, inst, resolve(inst, nets), seed=0)
    (loser,) = sorted(result.unrouted)
    (winner,) = result.routed
    ex = explain_net(board, inst, nets, loser, routing=result.routing)
    taken = next(b for b in ex.pairs[0].blockers if b.column == 4)
    assert taken.net_id == winner
    assert f"strip {winner}" in str(ex)


def test_a_single_row_net_has_no_pairs_and_no_detour_rows():
    inst = [ComponentInstance("A1", PIN, origin=(2, 4)),
            ComponentInstance("A2", PIN, origin=(8, 4))]
    nets = [Net("A", frozenset({("A1", "1"), ("A2", "1")}))]
    ex = explain_net(BOARD, inst, nets, "A")
    assert ex.pairs == () and ex.detour_rows == ()
    assert ex.routed


# ---- soundness: nothing is written off that could have routed -------------------------

@st.composite
def scattered_pins(draw):
    """A two-net board: pins dropped on a small grid, split between the nets."""
    board = Board(draw(st.integers(4, 9)), draw(st.integers(4, 8)))
    holes = draw(
        st.lists(
            st.tuples(st.integers(1, board.w), st.integers(1, board.h)),
            min_size=3, max_size=7, unique=True,
        )
    )
    inst, mine, theirs = [], set(), set()
    for i, hole in enumerate(holes):
        inst.append(ComponentInstance(f"P{i}", PIN, origin=hole))
        (mine if draw(st.booleans()) else theirs).add((f"P{i}", "1"))
    nets = [Net("A", frozenset(mine)), Net("B", frozenset(theirs))]
    return board, inst, [n for n in nets if n.pins]


@given(scattered_pins())
@settings(max_examples=250, deadline=None)
def test_a_flagged_net_really_cannot_be_routed(problem):
    """The check skips the search for the nets it flags, so it must never flag a live one.

    Soundness is measured against component geometry alone: obstacles only ever grow as
    other nets are routed, so a net that cannot route on the bare placement cannot route
    on the finished board either.
    """
    board, inst, nets = problem
    resolved = resolve(inst, nets)
    pin_pos = pin_world_positions(inst)
    internal = internal_tie_pairs(inst)
    for net in resolved.nets:
        if not row_conflicts(net, pin_pos, resolved.pin_to_net):
            continue
        obstacles = build_obstacles(inst, Routing(), resolved.pin_to_net, net.id)
        assert route_net(board, net, pin_pos, internal, obstacles) is None, (
            f"{net.id} was flagged but routes: "
            f"{sorted((r, pin_pos[r]) for r in net.pins)}"
        )
