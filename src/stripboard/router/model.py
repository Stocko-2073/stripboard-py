"""Core entities: component templates/instances, nets, strips, jumpers, and the board.

Data model follows notes section 1, with one refinement: routed geometry
(strips, jumpers) lives in a separate mutable :class:`Routing` container rather than on
:class:`Net`, so that cost/validation stay pure functions of ``(board, instances,
routing)`` and rip-up/reroute can try candidates without mutating the netlist.

Cuts are never stored -- they are derived from strip extents (see :mod:`stripboard.router.cuts`).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from .geometry import Point, Rect, flip_point

# A pin is identified across placement by (instance_id, local_id) -- never by coordinate.
PinRef = tuple[str, str]


# --------------------------------------------------------------------------- templates


@dataclass(frozen=True)
class PinDef:
    """A pin in a component type's local coordinates (origin at ``(0, 0)``)."""

    local_id: str
    offset: Point


@dataclass(frozen=True)
class ComponentType:
    """A reusable footprint: pins, keep-out rectangles, and internal ties.

    ``internal`` groups local_ids that are electrically common inside the part. Such ties
    define net membership (spec section 2.5/2.7) and route with length 0.
    """

    name: str
    pins: tuple[PinDef, ...] = ()
    keepouts: tuple[Rect, ...] = ()
    internal: tuple[frozenset[str], ...] = ()

    def __post_init__(self) -> None:
        ids = [p.local_id for p in self.pins]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Component type {self.name!r} has duplicate pin local_ids.")
        known = set(ids)
        for group in self.internal:
            unknown = group - known
            if unknown:
                raise ValueError(
                    f"Component type {self.name!r} internal group references unknown pins "
                    f"{sorted(unknown)}."
                )

    def pin(self, local_id: str) -> PinDef:
        for p in self.pins:
            if p.local_id == local_id:
                return p
        raise KeyError(f"Component type {self.name!r} has no pin {local_id!r}.")


# --------------------------------------------------------------------------- instances


@dataclass(frozen=True)
class ComponentInstance:
    """A placed occurrence of a :class:`ComponentType`.

    ``origin`` is the world position of the type's local origin; ``flipped`` applies the
    180-degree rotation of spec section 2.3. A ``locked`` instance keeps its ``origin`` and
    ``flipped`` fixed during placement.
    """

    id: str
    type: ComponentType
    origin: Point = (1, 1)
    flipped: bool = False
    locked: bool = False

    def _to_world(self, local: Point) -> Point:
        dx, dy = flip_point(local) if self.flipped else local
        return (self.origin[0] + dx, self.origin[1] + dy)

    def world_pins(self) -> dict[str, Point]:
        """Map each ``local_id`` to its placed world point."""
        return {p.local_id: self._to_world(p.offset) for p in self.type.pins}

    def world_keepouts(self) -> list[Rect]:
        """The instance's keep-out rectangles in world coordinates."""
        out: list[Rect] = []
        for r in self.type.keepouts:
            rr = r.flip() if self.flipped else r
            out.append(rr.translate(self.origin[0], self.origin[1]))
        return out

    def refs(self) -> list[PinRef]:
        return [(self.id, p.local_id) for p in self.type.pins]

    def moved(self, origin: Point, flipped: bool) -> ComponentInstance:
        """Return a copy relocated to ``origin``/``flipped`` (raises if locked)."""
        if self.locked:
            raise ValueError(f"Instance {self.id!r} is locked and cannot be moved.")
        return replace(self, origin=origin, flipped=flipped)


# --------------------------------------------------------------------------- nets


@dataclass(frozen=True)
class Net:
    """An electrical group of pins (input only). Routed geometry lives in :class:`Routing`."""

    id: str
    pins: frozenset[PinRef]
    weight: float = 1.0


# --------------------------------------------------------------------------- routed geometry


@dataclass(frozen=True)
class Strip:
    """A horizontal conductor on row ``y`` spanning columns ``[xa, xb]`` (spec section 2.1).

    Minimum size is a single point (``xa == xb``). On-board-ness is a validator concern,
    not enforced here, so partial layouts remain constructible during routing.
    """

    y: int
    xa: int
    xb: int
    net_id: str

    def __post_init__(self) -> None:
        if self.xa > self.xb:
            raise ValueError(f"Strip requires xa <= xb; got xa={self.xa}, xb={self.xb}.")

    def points_count(self) -> int:
        return self.xb - self.xa + 1

    def length(self) -> int:
        return self.xb - self.xa

    def points(self) -> Iterator[Point]:
        for x in range(self.xa, self.xb + 1):
            yield (x, self.y)

    def contains(self, p: Point) -> bool:
        return p[1] == self.y and self.xa <= p[0] <= self.xb

    def edge_cuts(self, w: int, h: int) -> set[Point]:
        """The on-board cut points immediately past each edge (spec section 5)."""
        cuts: set[Point] = set()
        for cx in (self.xa - 1, self.xb + 1):
            if 1 <= cx <= w and 1 <= self.y <= h:
                cuts.add((cx, self.y))
        return cuts


@dataclass(frozen=True)
class Jumper:
    """A vertical bridge in column ``x`` between rows ``ya < yb`` (spec section 2.2)."""

    x: int
    ya: int
    yb: int
    net_id: str

    def __post_init__(self) -> None:
        if self.ya >= self.yb:
            raise ValueError(f"Jumper requires ya < yb; got ya={self.ya}, yb={self.yb}.")

    def vlength(self) -> int:
        return self.yb - self.ya

    def endpoints(self) -> tuple[Point, Point]:
        return ((self.x, self.ya), (self.x, self.yb))

    def keepout(self) -> set[Point]:
        """Interior column cells the wire arcs over; empty when ``vlength == 1``."""
        return {(self.x, y) for y in range(self.ya + 1, self.yb)}


@dataclass
class Routing:
    """Mutable container for routed strips/jumpers, keyed by ``net_id``."""

    strips: dict[str, list[Strip]] = field(default_factory=dict)
    jumpers: dict[str, list[Jumper]] = field(default_factory=dict)

    def add_strip(self, s: Strip) -> None:
        self.strips.setdefault(s.net_id, []).append(s)

    def add_jumper(self, j: Jumper) -> None:
        self.jumpers.setdefault(j.net_id, []).append(j)

    def strips_of(self, net_id: str) -> list[Strip]:
        return self.strips.get(net_id, [])

    def jumpers_of(self, net_id: str) -> list[Jumper]:
        return self.jumpers.get(net_id, [])

    def rip_up(self, net_id: str) -> None:
        """Remove all strips and jumpers of a net, leaving only its pins (spec section 6)."""
        self.strips.pop(net_id, None)
        self.jumpers.pop(net_id, None)

    def all_strips(self) -> list[Strip]:
        return [s for group in self.strips.values() for s in group]

    def all_jumpers(self) -> list[Jumper]:
        return [j for group in self.jumpers.values() for j in group]

    def copy(self) -> Routing:
        """Deep-ish copy: fresh lists/dicts (entities are frozen, so shared safely)."""
        return Routing(
            strips={k: list(v) for k, v in self.strips.items()},
            jumpers={k: list(v) for k, v in self.jumpers.items()},
        )


# --------------------------------------------------------------------------- board & weights


@dataclass(frozen=True)
class Weights:
    """Objective weights (spec section 7; defaults from notes section 4)."""

    w_len: float = 1.0  # per grid unit of net length (electrical diameter)
    w_jmp: float = 10.0  # per jumper
    w_cut: float = 3.0  # per distinct physical cut
    w_x: float = 1.0  # placement: per unit horizontal span
    w_y: float = 5.0  # placement: per unit vertical span


@dataclass(frozen=True)
class Board:
    """The board: dimensions plus objective weights (spec section 7)."""

    w: int = 34
    h: int = 26
    weights: Weights = field(default_factory=Weights)

    def __post_init__(self) -> None:
        if self.w < 1 or self.h < 1:
            raise ValueError(f"Board dimensions must be >= 1; got w={self.w}, h={self.h}.")

    def in_bounds(self, p: Point) -> bool:
        x, y = p
        return 1 <= x <= self.w and 1 <= y <= self.h
