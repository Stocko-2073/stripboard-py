"""ComponentType / ComponentInstance transform and invariant tests (SPEC section 2.3)."""

from __future__ import annotations

import pytest

from stripboard.router.geometry import Rect
from stripboard.router.model import ComponentInstance, ComponentType, PinDef, Routing, Strip


def make_type() -> ComponentType:
    # A tiny 2-pin part with a body keep-out.
    return ComponentType(
        name="R",
        pins=(PinDef("1", (0, 0)), PinDef("2", (0, 3))),
        keepouts=(Rect.of(0, 1, 0, 2),),
    )


def test_world_pins_unflipped():
    inst = ComponentInstance("R1", make_type(), origin=(5, 10), flipped=False)
    assert inst.world_pins() == {"1": (5, 10), "2": (5, 13)}


def test_world_pins_flipped():
    inst = ComponentInstance("R1", make_type(), origin=(5, 10), flipped=True)
    # local (0,0)->(0,0); local (0,3)->(0,-3); then +origin
    assert inst.world_pins() == {"1": (5, 10), "2": (5, 7)}


def test_world_keepouts_flip_then_translate():
    inst = ComponentInstance("R1", make_type(), origin=(5, 10), flipped=True)
    # local [0,0]x[1,2] flips to [0,0]x[-2,-1], then +origin
    assert inst.world_keepouts() == [Rect(5, 8, 5, 9)]


def test_flip_is_involution_on_instance():
    t = make_type()
    a = ComponentInstance("R1", t, origin=(5, 10), flipped=False)
    b = ComponentInstance("R1", t, origin=(5, 10), flipped=True)
    # Flipping twice returns the same world pins as unflipped (about the origin).
    double = {lid: (2 * a.origin[0] - p[0], 2 * a.origin[1] - p[1]) for lid, p in b.world_pins().items()}
    assert double == a.world_pins()


def test_locked_instance_cannot_move():
    inst = ComponentInstance("R1", make_type(), locked=True)
    with pytest.raises(ValueError):
        inst.moved((2, 2), False)


def test_duplicate_pin_ids_rejected():
    with pytest.raises(ValueError):
        ComponentType("bad", pins=(PinDef("1", (0, 0)), PinDef("1", (0, 1))))


def test_internal_group_unknown_pin_rejected():
    with pytest.raises(ValueError):
        ComponentType("bad", pins=(PinDef("1", (0, 0)),), internal=(frozenset({"1", "9"}),))


def test_routing_rip_up():
    r = Routing()
    r.add_strip(Strip(4, 1, 3, "n"))
    r.add_strip(Strip(4, 1, 3, "m"))
    r.rip_up("n")
    assert r.strips_of("n") == []
    assert len(r.strips_of("m")) == 1


def test_routing_copy_is_independent():
    r = Routing()
    r.add_strip(Strip(4, 1, 3, "n"))
    c = r.copy()
    c.add_strip(Strip(5, 1, 3, "n"))
    assert len(r.strips_of("n")) == 1
    assert len(c.strips_of("n")) == 2
