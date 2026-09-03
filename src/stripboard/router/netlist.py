"""Netlist resolution (spec section 2.5 / 2.7) -- Phase 0.

Turns raw input (component instances + a netlist of pin references) into resolved nets:

1. Close net membership over ``internal`` ties: internal ties define electrical
   commonality inside a part, so every pin tied to a listed pin joins that pin's net.
2. Synthesize a trivial ``NET_<inst>_<local>`` net for every pin not otherwise assigned,
   so even NC / mechanical pins get a (single-point) strip.
3. Validate the input: unknown pin references, duplicate ids, and -- the key rule --
   two internally-tied pins listed in *different* nets, which is an input error.

Resolution is placement-independent: nets reference pins by identity ``(instance_id,
local_id)``, never by coordinate. World positions are looked up separately from the
current instance placements.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import ComponentInstance, Net, PinRef


class NetlistError(ValueError):
    """Raised for inconsistent netlist input (spec section 2.7)."""


@dataclass(frozen=True)
class ResolvedNet:
    id: str
    pins: frozenset[PinRef]
    weight: float = 1.0


@dataclass(frozen=True)
class ResolvedNetlist:
    nets: tuple[ResolvedNet, ...]
    pin_to_net: dict[PinRef, str]

    def net(self, net_id: str) -> ResolvedNet:
        for n in self.nets:
            if n.id == net_id:
                return n
        raise KeyError(net_id)


class _UnionFind:
    def __init__(self, items: list[PinRef]) -> None:
        self.parent: dict[PinRef, PinRef] = {i: i for i in items}

    def find(self, a: PinRef) -> PinRef:
        root = a
        while self.parent[root] != root:
            root = self.parent[root]
        # path compression
        while self.parent[a] != root:
            self.parent[a], a = root, self.parent[a]
        return root

    def union(self, a: PinRef, b: PinRef) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # deterministic: smaller ref becomes root
        lo, hi = (ra, rb) if ra < rb else (rb, ra)
        self.parent[hi] = lo


def resolve(instances: list[ComponentInstance], netlist: list[Net]) -> ResolvedNetlist:
    """Resolve raw instances + netlist into :class:`ResolvedNetlist` (spec section 2.7)."""
    # --- index instances and known pin refs -----------------------------------------
    seen_ids: set[str] = set()
    all_pins: list[PinRef] = []
    for inst in instances:
        if inst.id in seen_ids:
            raise NetlistError(f"Duplicate component instance id {inst.id!r}.")
        seen_ids.add(inst.id)
        all_pins.extend(inst.refs())
    known = set(all_pins)

    # --- internal-tie equivalence classes -------------------------------------------
    uf = _UnionFind(all_pins)
    for inst in instances:
        for group in inst.type.internal:
            members = [(inst.id, lid) for lid in sorted(group)]
            for other in members[1:]:
                uf.union(members[0], other)

    # --- validate + assign explicit nets to classes ---------------------------------
    seen_net_ids: set[str] = set()
    weight_by_net: dict[str, float] = {}
    class_net: dict[PinRef, str] = {}  # class root -> explicit net id
    for net in netlist:
        if net.id in seen_net_ids:
            raise NetlistError(f"Duplicate net id {net.id!r}.")
        seen_net_ids.add(net.id)
        weight_by_net[net.id] = net.weight
        for ref in net.pins:
            if ref not in known:
                raise NetlistError(
                    f"Net {net.id!r} references unknown pin {ref!r} "
                    "(no such instance/local_id)."
                )
            root = uf.find(ref)
            prior = class_net.get(root)
            if prior is not None and prior != net.id:
                raise NetlistError(
                    f"Pin {ref!r} is internally tied to a pin already in net {prior!r} "
                    f"but is listed in net {net.id!r}; internally-tied pins cannot span nets."
                )
            class_net[root] = net.id

    # --- group pins by resolved net (explicit or synthesized trivial) ---------------
    pins_by_net: dict[str, set[PinRef]] = {net.id: set() for net in netlist}
    pin_to_net: dict[PinRef, str] = {}
    for ref in all_pins:
        root = uf.find(ref)
        net_id = class_net.get(root)
        if net_id is None:
            # Trivial net for this internal-tie class, named after its representative pin.
            rep = root
            net_id = f"NET_{rep[0]}_{rep[1]}"
            class_net[root] = net_id
            weight_by_net.setdefault(net_id, 1.0)
            pins_by_net.setdefault(net_id, set())
        pins_by_net.setdefault(net_id, set()).add(ref)
        pin_to_net[ref] = net_id

    nets = tuple(
        ResolvedNet(id=nid, pins=frozenset(pins), weight=weight_by_net.get(nid, 1.0))
        for nid, pins in sorted(pins_by_net.items())
    )
    return ResolvedNetlist(nets=nets, pin_to_net=pin_to_net)


def internal_tie_pairs(instances: list[ComponentInstance]) -> list[tuple[PinRef, PinRef]]:
    """All length-0 internal-tie connections as (rep, other) pin-ref pairs (spec section 2.5)."""
    pairs: list[tuple[PinRef, PinRef]] = []
    for inst in instances:
        for group in inst.type.internal:
            members = [(inst.id, lid) for lid in sorted(group)]
            for other in members[1:]:
                pairs.append((members[0], other))
    return pairs


def pin_world_positions(instances: list[ComponentInstance]) -> dict[PinRef, tuple[int, int]]:
    """Current world position of every pin, given the instances' placements."""
    out: dict[PinRef, tuple[int, int]] = {}
    for inst in instances:
        for lid, p in inst.world_pins().items():
            out[(inst.id, lid)] = p
    return out
