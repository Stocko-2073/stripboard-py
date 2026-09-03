"""Occupancy index: per-point owners on two layers (spec section 3).

Occupied points are of two kinds:

* **conductive** -- strip cells, pins, and jumper endpoints (carry signal);
* **clearance** -- a jumper's keep-out arc and component keep-outs (reserved, non-conductive).

Collisions are defined only conductive-vs-conductive across nets (spec section 3.4);
the clearance layer drives the keep-out rules (spec section 3.1). This index is a small
dict-of-lists per layer, cheap to (re)build at this scale (<= ~884 cells), and is used by
both the validator and the router.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Point
from .model import ComponentInstance, Jumper, PinRef, Routing, Strip


@dataclass(frozen=True)
class Occupant:
    """One entity occupying a point."""

    kind: str  # "strip" | "pin" | "jumper_end" | "jumper_arc" | "keepout"
    net_id: str | None  # None for component keep-outs
    comp_id: str | None  # owning instance, for pins and keep-outs; else None
    key: str  # stable identity, so an entity is never compared against itself


class OccupancyIndex:
    """Two point->occupants layers (conductive, clearance)."""

    def __init__(self) -> None:
        self.conductive: dict[Point, list[Occupant]] = {}
        self.clearance: dict[Point, list[Occupant]] = {}

    # --- construction ---------------------------------------------------------------

    def _add(self, layer: dict[Point, list[Occupant]], p: Point, occ: Occupant) -> None:
        layer.setdefault(p, []).append(occ)

    def add_strip(self, strip: Strip, key: str) -> None:
        occ = Occupant("strip", strip.net_id, None, key)
        for p in strip.points():
            self._add(self.conductive, p, occ)

    def add_pin(self, ref: PinRef, pos: Point, net_id: str) -> None:
        self._add(self.conductive, pos, Occupant("pin", net_id, ref[0], f"pin:{ref[0]}:{ref[1]}"))

    def add_jumper(self, jumper: Jumper, key: str) -> None:
        end = Occupant("jumper_end", jumper.net_id, None, key)
        for p in jumper.endpoints():
            self._add(self.conductive, p, end)
        arc = Occupant("jumper_arc", jumper.net_id, None, key)
        for p in jumper.keepout():
            self._add(self.clearance, p, arc)

    def add_keepout(self, comp_id: str, points: list[Point], key: str) -> None:
        occ = Occupant("keepout", None, comp_id, key)
        for p in points:
            self._add(self.clearance, p, occ)

    # --- queries (used by the router) -----------------------------------------------

    def conductive_nets_at(self, p: Point) -> set[str]:
        return {o.net_id for o in self.conductive.get(p, ()) if o.net_id is not None}

    def is_conductive(self, p: Point) -> bool:
        return p in self.conductive

    def is_clearance(self, p: Point) -> bool:
        return p in self.clearance

    def occupied_points(self) -> set[Point]:
        return set(self.conductive) | set(self.clearance)


def build_index(
    instances: list[ComponentInstance],
    routing: Routing,
    pin_to_net: dict[PinRef, str],
) -> OccupancyIndex:
    """Build a full occupancy index from placed instances and routed geometry."""
    idx = OccupancyIndex()
    for inst in instances:
        for lid, pos in inst.world_pins().items():
            ref = (inst.id, lid)
            idx.add_pin(ref, pos, pin_to_net.get(ref, f"NET_{inst.id}_{lid}"))
        for ri, rect in enumerate(inst.world_keepouts()):
            idx.add_keepout(inst.id, list(rect.points()), f"ko:{inst.id}:{ri}")
    for net_id, strips in routing.strips.items():
        for si, s in enumerate(strips):
            idx.add_strip(s, f"strip:{net_id}:{si}")
    for net_id, jumpers in routing.jumpers.items():
        for ji, j in enumerate(jumpers):
            idx.add_jumper(j, f"jmp:{net_id}:{ji}")
    return idx


def build_obstacles(
    instances: list[ComponentInstance],
    routing: Routing,
    pin_to_net: dict[PinRef, str],
    exclude_net_id: str,
) -> OccupancyIndex:
    """Occupancy of everything the net ``exclude_net_id`` must avoid.

    Includes every component keep-out (clearance, all nets) plus the conductive geometry
    (pins, strips, jumpers) of all *other* nets. The excluded net's own pins/geometry are
    left out -- the router checks those against itself.
    """
    idx = OccupancyIndex()
    for inst in instances:
        for lid, pos in inst.world_pins().items():
            ref = (inst.id, lid)
            net_id = pin_to_net.get(ref, f"NET_{inst.id}_{lid}")
            if net_id != exclude_net_id:
                idx.add_pin(ref, pos, net_id)
        for ri, rect in enumerate(inst.world_keepouts()):
            idx.add_keepout(inst.id, list(rect.points()), f"ko:{inst.id}:{ri}")
    for net_id, strips in routing.strips.items():
        if net_id == exclude_net_id:
            continue
        for si, s in enumerate(strips):
            idx.add_strip(s, f"strip:{net_id}:{si}")
    for net_id, jumpers in routing.jumpers.items():
        if net_id == exclude_net_id:
            continue
        for ji, j in enumerate(jumpers):
            idx.add_jumper(j, f"jmp:{net_id}:{ji}")
    return idx
