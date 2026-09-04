"""Why a net cannot be routed.

Infeasibility is data rather than an exception, but "this net did not route" is only
actionable with a reason attached, and the reason is almost always geometric: some hole
the net needs is taken, or some pair of its rows has nowhere left to bridge.

:func:`row_conflicts` catches the failures that need no search at all. A net with pins on
a row gets a strip covering at least its own outermost pins there, and that strip's track
cuts land on the columns immediately outside it. So a foreign pin anywhere from one column
left of the net's leftmost pin to one column right of its rightmost is fatal: covering it
would short two nets, and cutting on it is not a cut. No topology, jumper column or detour
row escapes it either, since a detour adds a row rather than shrinking an existing one's
span. The check is complete for those cases and cheap -- it reads pin positions and net
membership, nothing else.

:func:`explain_net` goes further and routes one net on its own, reporting the feasibility
the search works from: which pairs of the net's rows a jumper can bridge at all, in which
columns, and what occupies the columns of a pair that has none. Given a solved
:class:`~stripboard.router.model.Routing` it answers that against the finished board --
who took the column this net needed -- and without one, against the parts alone, which
says whether the net could ever route on this placement.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Point
from .model import Board, ComponentInstance, Jumper, Net, PinRef, Routing
from .netlist import ResolvedNet, internal_tie_pairs, pin_world_positions, resolve
from .occupancy import OccupancyIndex, build_obstacles
from .routing.net_router import feasible_columns, route_net, steiner_row_candidates

__all__ = [
    "Blocker",
    "NetExplanation",
    "RowPair",
    "RowPins",
    "RowConflict",
    "conflict_reason",
    "explain_net",
    "row_conflicts",
]

# A fully-blocked row pair on a wide board would otherwise print one line per column.
_MAX_BLOCKERS = 12


@dataclass(frozen=True)
class RowConflict:
    """A foreign pin within reach of the strip a net needs on one of its rows."""

    net_id: str
    row: int
    span: tuple[int, int]  # the net's own outermost pin columns on that row
    blocker: PinRef
    blocker_pos: Point
    blocker_net: str

    @property
    def message(self) -> str:
        lo, hi = self.span
        inst, local_id = self.blocker
        bx, by = self.blocker_pos
        who = f"{inst}.{local_id} at ({bx},{by}) (net {self.blocker_net})"
        if lo != hi:
            mine, needs = f"pins ({lo},{self.row}) and ({hi},{self.row})", "need"
        else:
            mine, needs = f"pin ({lo},{self.row})", "needs"
        if lo < bx < hi:
            return (
                f"{mine} share row {self.row}, but {who} lies between them, so this "
                f"net's row-{self.row} strip would have to cover it"
            )
        return (
            f"{mine} {needs} row {self.row}, but {who} is immediately alongside, so "
            f"this net's row-{self.row} strip has nowhere to cut clear of it"
        )


def row_conflicts(
    net: ResolvedNet,
    pin_pos: dict[PinRef, Point],
    pin_to_net: dict[PinRef, str],
) -> list[RowConflict]:
    """Every foreign pin within reach of one of ``net``'s per-row strips.

    Depends on placement but not on routing, so the answer holds however the other nets
    are routed and can be computed once per placement. Only pins count: a strip may
    legally run under a component keep-out, and another net's strips and jumpers move.
    """
    own_by_row: dict[int, list[int]] = {}
    for ref in net.pins:
        x, y = pin_pos[ref]
        own_by_row.setdefault(y, []).append(x)

    found: list[RowConflict] = []
    for row, xs in sorted(own_by_row.items()):
        lo, hi = min(xs), max(xs)
        for ref, (x, y) in sorted(pin_pos.items()):
            # lo - 1 and hi + 1 are where this row's strip has to put its cuts.
            if y != row or not lo - 1 <= x <= hi + 1 or ref in net.pins:
                continue
            found.append(
                RowConflict(
                    net_id=net.id,
                    row=row,
                    span=(lo, hi),
                    blocker=ref,
                    blocker_pos=(x, y),
                    blocker_net=pin_to_net[ref],
                )
            )
    return found


def conflict_reason(conflicts: list[RowConflict]) -> str:
    """One net's row conflicts as a single reason string."""
    reason = conflicts[0].message
    extra = len(conflicts) - 1
    if extra:
        reason += f"; {extra} further pin{'s' if extra > 1 else ''} trapped like this"
    return reason


@dataclass(frozen=True)
class RowPins:
    """One row a net occupies, and the columns of its pins there."""

    row: int
    columns: tuple[int, ...]


@dataclass(frozen=True)
class Blocker:
    """The first occupied cell a jumper in one column would have run into."""

    column: int
    point: Point
    # An occupancy kind ("pin", "strip", "jumper_end", "jumper_arc", "keepout"), or
    # "own pin" -- a wire end may not share a hole with a pin even of its own net.
    kind: str
    net_id: str | None
    comp_id: str | None

    @property
    def label(self) -> str:
        owner = self.comp_id or self.net_id
        return f"{self.kind} {owner}" if owner else self.kind


@dataclass(frozen=True)
class RowPair:
    """Two of a net's rows, and the columns in which a jumper could bridge them."""

    ya: int
    yb: int
    columns: tuple[int, ...]
    blockers: tuple[Blocker, ...] = ()  # populated only when there are no columns


@dataclass(frozen=True)
class NetExplanation:
    """Everything the per-net search knows about one net's geometry."""

    net_id: str
    pins: tuple[RowPins, ...]
    conflicts: tuple[RowConflict, ...]
    pairs: tuple[RowPair, ...]
    detour_rows: tuple[int, ...]
    routed: bool
    in_context: bool

    @property
    def pin_count(self) -> int:
        return sum(len(r.columns) for r in self.pins)

    def __str__(self) -> str:
        against = "the routed board" if self.in_context else "the parts alone"
        out = [
            f"net {self.net_id} -- {self.pin_count} pins on {len(self.pins)} "
            f"row{'s' if len(self.pins) != 1 else ''}, against {against}",
            "",
        ]
        for r in self.pins:
            out.append(f"  row {r.row:>3}  columns {', '.join(str(c) for c in r.columns)}")

        for c in self.conflicts:
            out += ["", f"  TRAPPED  {c.message}"]

        if self.pairs:
            out += ["", "feasible jumper columns"]
            for pair in self.pairs:
                head = f"  rows {pair.ya:>3}-{pair.yb:<3}"
                if pair.columns:
                    cols = " ".join(str(c) for c in pair.columns)
                    out.append(f"{head} {len(pair.columns):>3}: {cols}")
                else:
                    out.append(f"{head} none")
            for pair in self.pairs:
                if pair.columns or not pair.blockers:
                    continue
                out += ["", f"rows {pair.ya} and {pair.yb} cannot be bridged; what is in the way"]
                for b in pair.blockers[:_MAX_BLOCKERS]:
                    out.append(f"  col {b.column:>3}  {b.label} at {b.point}")
                if len(pair.blockers) > _MAX_BLOCKERS:
                    out.append(f"  ... {len(pair.blockers) - _MAX_BLOCKERS} more columns")

        if self.detour_rows:
            out += ["", f"detour rows tried on failure: "
                        f"{', '.join(str(r) for r in self.detour_rows)}"]
        out += ["", f"routes here: {'yes' if self.routed else 'no'}"]
        return "\n".join(out)


def _first_blocker(
    j: Jumper, obstacles: OccupancyIndex, own_pins: set[Point]
) -> Blocker | None:
    """The first occupied cell along a jumper, scanning from its top endpoint down.

    A report of what is present, not a re-derivation of the validity rules -- a cell
    listed here is one the wire would have to share, whichever rule forbids it.
    """
    for p in ((j.x, j.ya), *sorted(j.keepout()), (j.x, j.yb)):
        if p in own_pins:
            return Blocker(j.x, p, "own pin", None, None)
        for layer in (obstacles.conductive, obstacles.clearance):
            occupants = layer.get(p)
            if occupants:
                occ = occupants[0]
                return Blocker(j.x, p, occ.kind, occ.net_id, occ.comp_id)
    return None


def explain_net(
    board: Board,
    instances: list[ComponentInstance],
    netlist: list[Net],
    net_id: str,
    *,
    routing: Routing | None = None,
) -> NetExplanation:
    """Route one net on its own and report the feasibility it was searched against.

    Without ``routing`` the net meets component geometry only -- pins and keep-outs --
    which answers whether it could route on this placement at all. Pass a solved
    ``Routing`` and every other net's strips and jumpers join the obstacles, which
    answers which of them took the columns this net needed. The net's own geometry is
    never an obstacle to itself in either case.
    """
    resolved = resolve(instances, netlist)
    net = resolved.net(net_id)
    pin_pos = pin_world_positions(instances)
    obstacles = build_obstacles(
        instances, routing if routing is not None else Routing(), resolved.pin_to_net, net_id
    )
    own_pins = {pin_pos[ref] for ref in net.pins}

    by_row: dict[int, list[int]] = {}
    for ref in net.pins:
        x, y = pin_pos[ref]
        by_row.setdefault(y, []).append(x)
    rows = sorted(by_row)

    pairs: list[RowPair] = []
    for i, ya in enumerate(rows):
        for yb in rows[i + 1:]:
            columns = feasible_columns(board, net_id, ya, yb, obstacles, own_pins)
            blockers: tuple[Blocker, ...] = ()
            if not columns:
                found = (_first_blocker(Jumper(c, ya, yb, net_id), obstacles, own_pins)
                         for c in range(1, board.w + 1))
                blockers = tuple(b for b in found if b is not None)
            pairs.append(RowPair(ya, yb, tuple(columns), blockers))

    routed = route_net(
        board, net, pin_pos, internal_tie_pairs(instances), obstacles
    ) is not None

    return NetExplanation(
        net_id=net_id,
        pins=tuple(RowPins(y, tuple(sorted(by_row[y]))) for y in rows),
        conflicts=tuple(row_conflicts(net, pin_pos, resolved.pin_to_net)),
        pairs=tuple(pairs),
        detour_rows=tuple(steiner_row_candidates(board.h, rows)) if len(rows) > 1 else (),
        routed=routed,
        in_context=routing is not None,
    )
