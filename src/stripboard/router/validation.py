"""Independent layout validator -- the spec section 8 checklist.

This is deliberately a *separate* implementation from the router, so it can act as an
oracle: run the router, then validate its output. It re-derives everything (net
membership, occupancy, cuts, connectivity) from ``(board, instances, netlist, routing)``
and reports every violated invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cuts import physical_cuts
from .geometry import Point
from .model import Board, ComponentInstance, Net, PinRef, Routing
from .netlist import resolve


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    points: tuple[Point, ...] = ()


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def __bool__(self) -> bool:
        return self.ok

    def add(self, code: str, message: str, points: tuple[Point, ...] = ()) -> None:
        self.violations.append(Violation(code, message, points))

    def summary(self) -> str:
        if self.ok:
            return "valid"
        return f"{len(self.violations)} violation(s): " + "; ".join(
            v.code for v in self.violations
        )


class _UF:
    def __init__(self) -> None:
        self.parent: dict[object, object] = {}

    def add(self, x: object) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: object) -> object:
        self.add(x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: object, b: object) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def validate(
    board: Board,
    instances: list[ComponentInstance],
    netlist: list[Net],
    routing: Routing,
) -> ValidationResult:
    """Validate a full layout against the spec section 8 checklist."""
    res = ValidationResult()
    resolved = resolve(instances, netlist)
    pin_net = resolved.pin_to_net

    # Placement snapshot: pin positions and per-instance keep-outs.
    pin_pos: dict[PinRef, Point] = {}
    for inst in instances:
        for lid, pos in inst.world_pins().items():
            pin_pos[(inst.id, lid)] = pos
    keepouts: list[tuple[str, set[Point]]] = [
        (inst.id, set(r.points())) for inst in instances for r in inst.world_keepouts()
    ]

    strips = routing.all_strips()
    jumpers = routing.all_jumpers()
    w, h = board.w, board.h

    # --- Rule 1: everything on board (cuts may fall off) ----------------------------
    for ref, p in pin_pos.items():
        if not board.in_bounds(p):
            res.add("offboard_pin", f"Pin {ref} at {p} is off board.", (p,))
    for s in strips:
        if not (1 <= s.xa and s.xb <= w and 1 <= s.y <= h):
            res.add("offboard_strip", f"Strip {s} extends off board.")
    for j in jumpers:
        if not (1 <= j.x <= w and 1 <= j.ya and j.yb <= h):
            res.add("offboard_jumper", f"Jumper {j} extends off board.")
    for cid, pts in keepouts:
        for p in pts:
            if not board.in_bounds(p):
                res.add("offboard_keepout", f"Keep-out of {cid} at {p} is off board.", (p,))
                break

    # --- Rules 2 & 3: minimum sizes (constructors already enforce, but verify) -------
    for s in strips:
        if s.points_count() < 1:
            res.add("strip_too_small", f"Strip {s} has < 1 point.")
    for j in jumpers:
        if j.vlength() < 1:
            res.add("jumper_too_small", f"Jumper {j} has vlength < 1.")

    # --- Build point maps -----------------------------------------------------------
    strip_at: dict[Point, list] = {}
    for s in strips:
        for p in s.points():
            strip_at.setdefault(p, []).append(s)
    pin_at: dict[Point, list[PinRef]] = {}
    for ref, p in pin_pos.items():
        pin_at.setdefault(p, []).append(ref)
    end_at: dict[Point, list] = {}
    arc_at: dict[Point, list] = {}
    for j in jumpers:
        for p in j.endpoints():
            end_at.setdefault(p, []).append(j)
        for p in j.keepout():
            arc_at.setdefault(p, []).append(j)
    keepout_at: dict[Point, list[str]] = {}
    for cid, pts in keepouts:
        for p in pts:
            keepout_at.setdefault(p, []).append(cid)

    # --- Rule 4a: same-row strip gap (>= 1 empty column), covers strip-strip overlap -
    by_row: dict[int, list] = {}
    for s in strips:
        by_row.setdefault(s.y, []).append(s)
    for y, row_strips in by_row.items():
        ordered = sorted(row_strips, key=lambda s: (s.xa, s.xb))
        for a, b in zip(ordered, ordered[1:], strict=False):
            if b.xa <= a.xb + 1:
                res.add(
                    "same_row_gap",
                    f"Strips on row {y} must have >=1 empty column between them: "
                    f"[{a.xa},{a.xb}] and [{b.xa},{b.xb}].",
                )

    # --- Rule 4b..: keep-out / jumper / pin forbidden overlaps -----------------------
    def _diff_component(a: str | None, b: str | None) -> bool:
        # Never check a component against its own authored geometry.
        return a is None or b is None or a != b

    all_points = (
        set(strip_at) | set(pin_at) | set(end_at) | set(arc_at) | set(keepout_at)
    )
    for p in all_points:
        pins_here = pin_at.get(p, [])
        ends_here = end_at.get(p, [])
        arcs_here = arc_at.get(p, [])
        kos_here = keepout_at.get(p, [])
        strips_here = strip_at.get(p, [])

        # pin ∩ pin (distinct instances)
        for i in range(len(pins_here)):
            for k in range(i + 1, len(pins_here)):
                if pins_here[i][0] != pins_here[k][0]:
                    res.add("pin_pin", f"Pins {pins_here[i]} and {pins_here[k]} overlap.", (p,))
        # keep-out ∩ keep-out (distinct instances)
        for i in range(len(kos_here)):
            for k in range(i + 1, len(kos_here)):
                if kos_here[i] != kos_here[k]:
                    res.add(
                        "keepout_keepout",
                        f"Keep-outs {kos_here[i]}/{kos_here[k]} overlap.",
                        (p,),
                    )
        # pin ∩ keep-out (distinct instances)
        for ref in pins_here:
            for cid in kos_here:
                if _diff_component(ref[0], cid):
                    res.add("pin_keepout", f"Pin {ref} overlaps keep-out of {cid}.", (p,))
        # jumper (endpoint or arc) ∩ keep-out
        if kos_here and (ends_here or arcs_here):
            res.add("jumper_keepout", f"Jumper overlaps a component keep-out at {p}.", (p,))
        # pin ∩ jumper (endpoint or arc)
        if pins_here and (ends_here or arcs_here):
            res.add("pin_jumper", f"Pin overlaps a jumper at {p}.", (p,))
        # jumper ∩ jumper (distinct jumpers, endpoint or arc)
        jset = {id(j) for j in ends_here} | {id(j) for j in arcs_here}
        if len(jset) > 1:
            res.add("jumper_jumper", f"Two jumpers overlap at {p}.", (p,))

        # --- Rule 5: cross-net conductive collision / inter-net connection ----------
        cond_nets: set[str] = set()
        cond_nets |= {strip_at_s.net_id for strip_at_s in strips_here}
        cond_nets |= {pin_net[ref] for ref in pins_here}
        cond_nets |= {j.net_id for j in ends_here}
        if len(cond_nets) > 1:
            res.add(
                "cross_net",
                f"Conductive point {p} shared by nets {sorted(cond_nets)}.",
                (p,),
            )

    # --- Rule 6: every pin lies on a strip of its own net ---------------------------
    for ref, p in pin_pos.items():
        net = pin_net[ref]
        if not any(s.net_id == net and s.contains(p) for s in strips_at_point(strip_at, p)):
            res.add("pin_not_on_strip", f"Pin {ref} at {p} not on a strip of net {net}.", (p,))

    # --- Rule 7: no dangling jumpers (each endpoint on a strip of its net) -----------
    for j in jumpers:
        for ep in j.endpoints():
            on_net_strip = any(
                s.net_id == j.net_id and s.contains(ep) for s in strips_at_point(strip_at, ep)
            )
            if not on_net_strip:
                res.add(
                    "dangling_jumper",
                    f"Jumper {j} endpoint {ep} not on a strip of its net.",
                    (ep,),
                )

    # --- Rule 8: every net fully connected ------------------------------------------
    _check_connectivity(res, instances, resolved, pin_pos, routing)

    # --- Rule 9: no derived cut coincides with a pin or jumper endpoint --------------
    cuts = physical_cuts(strips, w, h)
    pin_points = set(pin_pos.values())
    end_points = {ep for j in jumpers for ep in j.endpoints()}
    for c in cuts:
        if c in pin_points:
            res.add("cut_on_pin", f"Cut at {c} coincides with a pin.", (c,))
        if c in end_points:
            res.add("cut_on_endpoint", f"Cut at {c} coincides with a jumper endpoint.", (c,))

    return res


def strips_at_point(strip_at: dict[Point, list], p: Point) -> list:
    return strip_at.get(p, [])


def _check_connectivity(res, instances, resolved, pin_pos, routing) -> None:
    """Rule 8: each net's pins must form a single connected component (spec section 4.2)."""
    # Internal ties: length-0 connections between tied pins.
    internal_pairs: list[tuple[PinRef, PinRef]] = []
    for inst in instances:
        for group in inst.type.internal:
            members = [(inst.id, lid) for lid in sorted(group)]
            for other in members[1:]:
                internal_pairs.append((members[0], other))

    for net in resolved.nets:
        pins = sorted(net.pins)
        if len(pins) <= 1:
            continue
        uf = _UF()
        for ref in pins:
            uf.add(("pin", ref))
        # internal ties within this net
        for a, b in internal_pairs:
            if a in net.pins and b in net.pins:
                uf.union(("pin", a), ("pin", b))
        strips = routing.strips_of(net.id)
        jumpers = routing.jumpers_of(net.id)
        # Register jumper endpoint sites.
        for ji in range(len(jumpers)):
            uf.add(("end", ji, 0))
            uf.add(("end", ji, 1))
            uf.union(("end", ji, 0), ("end", ji, 1))
        # Sites sharing a strip are all connected.
        for s in strips:
            on_strip: list = []
            for ref in pins:
                if s.contains(pin_pos[ref]):
                    on_strip.append(("pin", ref))
            for ji, j in enumerate(jumpers):
                for ei, ep in enumerate(j.endpoints()):
                    if s.contains(ep):
                        on_strip.append(("end", ji, ei))
            for site in on_strip[1:]:
                uf.union(on_strip[0], site)
        roots = {uf.find(("pin", ref)) for ref in pins}
        if len(roots) > 1:
            res.add("not_connected", f"Net {net.id} is not fully connected ({len(roots)} parts).")
