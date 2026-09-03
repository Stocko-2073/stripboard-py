"""Netlist resolution tests (SPEC section 2.7)."""

from __future__ import annotations

import pytest

from stripboard.router.model import ComponentInstance, ComponentType, Net, PinDef
from stripboard.router.netlist import NetlistError, resolve


def chip(internal=()):
    return ComponentType(
        name="U",
        pins=(PinDef("A", (0, 0)), PinDef("B", (0, 1)), PinDef("C", (0, 2))),
        internal=internal,
    )


def test_explicit_membership():
    u = ComponentInstance("U1", chip())
    r = resolve([u], [Net("N1", frozenset({("U1", "A"), ("U1", "B")}))])
    assert r.pin_to_net[("U1", "A")] == "N1"
    assert r.pin_to_net[("U1", "B")] == "N1"
    # C is unassigned -> trivial net
    assert r.pin_to_net[("U1", "C")] == "NET_U1_C"


def test_internal_tie_extends_membership():
    # A and C internally tied; listing A in N1 pulls C into N1 too.
    u = ComponentInstance("U1", chip(internal=(frozenset({"A", "C"}),)))
    r = resolve([u], [Net("N1", frozenset({("U1", "A")}))])
    assert r.pin_to_net[("U1", "A")] == "N1"
    assert r.pin_to_net[("U1", "C")] == "N1"
    n1 = r.net("N1")
    assert ("U1", "C") in n1.pins


def test_internal_tie_unassigned_shares_trivial_net():
    # A and B tied, neither listed -> one shared trivial net, not two.
    u = ComponentInstance("U1", chip(internal=(frozenset({"A", "B"}),)))
    r = resolve([u], [])
    assert r.pin_to_net[("U1", "A")] == r.pin_to_net[("U1", "B")]


def test_trivial_net_per_unassigned_pin():
    u = ComponentInstance("U1", chip())
    r = resolve([u], [])
    ids = {r.pin_to_net[("U1", lid)] for lid in ("A", "B", "C")}
    assert ids == {"NET_U1_A", "NET_U1_B", "NET_U1_C"}


def test_internal_tie_across_two_nets_raises():
    u = ComponentInstance("U1", chip(internal=(frozenset({"A", "C"}),)))
    with pytest.raises(NetlistError):
        resolve([u], [Net("N1", frozenset({("U1", "A")})), Net("N2", frozenset({("U1", "C")}))])


def test_unknown_pin_ref_raises():
    u = ComponentInstance("U1", chip())
    with pytest.raises(NetlistError):
        resolve([u], [Net("N1", frozenset({("U1", "Z")}))])


def test_duplicate_instance_id_raises():
    with pytest.raises(NetlistError):
        resolve([ComponentInstance("U1", chip()), ComponentInstance("U1", chip())], [])


def test_duplicate_net_id_raises():
    u = ComponentInstance("U1", chip())
    with pytest.raises(NetlistError):
        resolve([u], [Net("N1", frozenset({("U1", "A")})), Net("N1", frozenset({("U1", "B")}))])


def test_weight_preserved():
    u = ComponentInstance("U1", chip())
    r = resolve([u], [Net("N1", frozenset({("U1", "A")}), weight=3.0)])
    assert r.net("N1").weight == 3.0


def test_every_pin_has_a_net():
    u1 = ComponentInstance("U1", chip())
    u2 = ComponentInstance("U2", chip())
    r = resolve([u1, u2], [Net("N1", frozenset({("U1", "A"), ("U2", "A")}))])
    for ref in u1.refs() + u2.refs():
        assert ref in r.pin_to_net
