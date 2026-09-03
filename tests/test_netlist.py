"""Netlist declaration: `net()` groups and `connect()` edges.

`net()` states a group of pins outright. `connect()` states one edge at a time, and
chained edges that share a pin have to merge into a single net -- otherwise the router
would be asked to route the same copper twice and would disagree with itself.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def parts(board):
    """Three 3-pin SIPs, far enough apart to leave routing room."""
    return (board.sip(2, "B", 3, "A", pins=["1", "2", "3"]),
            board.sip(8, "B", 3, "B", pins=["1", "2", "3"]),
            board.sip(14, "B", 3, "C", pins=["1", "2", "3"]))


def resolved(board) -> dict[str, set[tuple[str, str]]]:
    return {nid: set(refs) for nid, refs, _weight in board._resolve_nets()}


def test_net_declares_a_group_verbatim(board, parts):
    a, b, _ = parts
    board.net("GND", a.pin("1"), b.pin("1"))
    assert resolved(board) == {"GND": {("A", "1"), ("B", "1")}}


def test_net_returns_the_board_for_chaining(board, parts):
    a, b, _ = parts
    assert board.net("GND", a.pin("1"), b.pin("1")) is board


def test_net_deduplicates_repeated_pins(board, parts):
    a, b, _ = parts
    board.net("GND", a.pin("1"), b.pin("1"), a.pin("1"))
    assert resolved(board) == {"GND": {("A", "1"), ("B", "1")}}


def test_connect_makes_a_two_pin_net(board, parts):
    a, b, _ = parts
    board.connect(a.pin("1"), b.pin("1"))
    assert list(resolved(board).values()) == [{("A", "1"), ("B", "1")}]


def test_chained_connects_sharing_a_pin_merge_into_one_net(board, parts):
    """The union-find closure: A1-B1 and B1-C1 are one net, not two."""
    a, b, c = parts
    board.connect(a.pin("1"), b.pin("1"))
    board.connect(b.pin("1"), c.pin("1"))
    nets = resolved(board)
    assert len(nets) == 1
    assert next(iter(nets.values())) == {("A", "1"), ("B", "1"), ("C", "1")}


def test_transitively_linked_connects_merge_regardless_of_order(board, parts):
    """A1-B1 and C1-A1 declared out of order still close into one net."""
    a, b, c = parts
    board.connect(b.pin("1"), a.pin("1"))
    board.connect(c.pin("2"), b.pin("1"))
    nets = resolved(board)
    assert len(nets) == 1
    assert next(iter(nets.values())) == {("A", "1"), ("B", "1"), ("C", "2")}


def test_disjoint_connects_stay_separate(board, parts):
    a, b, c = parts
    board.connect(a.pin("1"), b.pin("1"))
    board.connect(b.pin("2"), c.pin("2"))
    nets = resolved(board)
    assert len(nets) == 2
    assert {frozenset(v) for v in nets.values()} == {
        frozenset({("A", "1"), ("B", "1")}),
        frozenset({("B", "2"), ("C", "2")}),
    }


def test_net_and_connect_coexist(board, parts):
    a, b, c = parts
    board.net("VCC", a.pin("3"), b.pin("3"))
    board.connect(a.pin("1"), c.pin("1"))
    nets = resolved(board)
    assert nets["VCC"] == {("A", "3"), ("B", "3")}
    assert len(nets) == 2


def test_resolution_partitions_the_declared_pins(board, parts):
    """Every declared pin lands in exactly one net -- no drops, no duplicates."""
    a, b, c = parts
    board.net("GND", a.pin("1"), b.pin("1"))
    board.connect(b.pin("2"), c.pin("2"))
    board.connect(c.pin("3"), a.pin("3"))
    groups = list(resolved(board).values())
    flat = [ref for g in groups for ref in g]
    assert len(flat) == len(set(flat)), "a pin must not appear in two nets"
    assert set(flat) == {("A", "1"), ("B", "1"), ("B", "2"),
                         ("C", "2"), ("C", "3"), ("A", "3")}


def test_net_colour_is_recorded(board, parts):
    a, b, _ = parts
    board.net("GND", a.pin("1"), b.pin("1"), color="k")
    assert board._net_colors["GND"] == "k"


def test_connect_colour_is_recorded_on_the_merged_net(board, parts):
    a, b, _ = parts
    board.connect(a.pin("1"), b.pin("1"), color="r")
    (net_id,) = resolved(board)
    assert board._net_colors[net_id] == "r"


def test_nets_reach_the_router(board, parts):
    a, b, _ = parts
    board.net("GND", a.pin("1"), b.pin("1"))
    _, _, netlist = board._build_problem()
    assert [(n.id, set(n.pins)) for n in netlist] == [("GND", {("A", "1"), ("B", "1")})]


def test_weights_are_carried_through(board, parts):
    a, b, _ = parts
    board.net("GND", a.pin("1"), b.pin("1"), weight=2.5)
    _, _, netlist = board._build_problem()
    assert netlist[0].weight == 2.5


@pytest.mark.parametrize("bad", [(3, 4), "A1", ["A", "1"], None, 7])
def test_pin_references_must_come_from_a_handle(board, parts, bad):
    a, _, _ = parts
    with pytest.raises(TypeError, match="expect pin references"):
        board.net("n", a.pin("1"), bad)
