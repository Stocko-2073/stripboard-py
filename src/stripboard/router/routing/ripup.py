"""Phase 2b -- global rip-up-and-reroute over net orderings.

Nets compete for rows and columns, so routing is a joint packing problem. We route nets
sequentially, each avoiding the geometry already placed (hard obstacles). When a net cannot
route, we rip up (start a fresh attempt) with a new ordering that prioritizes the nets that
failed, plus a seeded shuffle to escape local traps and polish cost. Congestion history
nudges routes to spread apart. The best attempt (most nets routed, then lowest cost) wins.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cost import cost_resolved
from ..geometry import Point
from ..model import Board, ComponentInstance, Routing, Strip, Weights
from ..netlist import ResolvedNet, ResolvedNetlist, internal_tie_pairs, pin_world_positions
from ..occupancy import build_obstacles
from ..rng import make_rng
from .congestion import NegotiatedCongestion
from .net_router import route_net


@dataclass(frozen=True)
class RipupOptions:
    max_attempts: int = 60
    patience: int = 8  # stop after this many all-routed attempts without cost improvement


@dataclass
class GlobalResult:
    routing: Routing
    routed: list[str]
    unrouted: dict[str, str]  # net_id -> reason


def _difficulty(net: ResolvedNet, pin_pos: dict) -> tuple[int, int, int]:
    pts = [pin_pos[r] for r in net.pins]
    rows = {p[1] for p in pts}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    area = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1) if pts else 0
    return (len(rows), len(net.pins), area)  # more rows / pins / area == harder


def _region_points(net: ResolvedNet, pin_pos: dict) -> list[Point]:
    return [pin_pos[r] for r in net.pins]


def route_nets(
    board: Board,
    instances: list[ComponentInstance],
    resolved: ResolvedNetlist,
    *,
    seed: int = 0,
    weights: Weights | None = None,
    options: RipupOptions | None = None,
) -> GlobalResult:
    """Route every net collision-free, resolving contention by rip-up + reordering."""
    opts = options or RipupOptions()
    w = weights if weights is not None else board.weights
    rng = make_rng(seed)
    pin_pos = pin_world_positions(instances)
    internal = internal_tie_pairs(instances)
    congestion = NegotiatedCongestion()

    # Hardest nets first.
    order = sorted(resolved.nets, key=lambda n: _difficulty(n, pin_pos), reverse=True)

    best: GlobalResult | None = None
    best_key: tuple[int, float] | None = None
    no_improve = 0

    for _attempt in range(opts.max_attempts):
        routing = Routing()
        unrouted: dict[str, str] = {}
        for net in order:
            obstacles = build_obstacles(instances, routing, resolved.pin_to_net, net.id)
            res = route_net(
                board, net, pin_pos, internal, obstacles, weights=w, congestion=congestion
            )
            if res is None:
                unrouted[net.id] = "no collision-free route found"
                congestion.penalize(_region_points(net, pin_pos))
                continue
            strips, jumpers = res
            for s in strips:
                routing.add_strip(s)
            for j in jumpers:
                routing.add_jumper(j)

        routed = [n.id for n in resolved.nets if n.id not in unrouted]
        cost = cost_resolved(board, instances, resolved, routing, weights=w).total
        key = (len(routed), -cost)
        improved = best_key is None or key > best_key
        if improved:
            best_key = key
            best = GlobalResult(routing.copy(), routed, dict(unrouted))

        if not unrouted:
            no_improve = 0 if improved else no_improve + 1
            if no_improve >= opts.patience:
                break

        order = _next_order(resolved, order, unrouted, pin_pos, rng)

    assert best is not None
    _add_forced_strips(board, instances, resolved, best)
    return best


def _next_order(resolved, order, unrouted, pin_pos, rng):
    """Prioritize failed nets, then a seeded shuffle of the rest."""
    if unrouted:
        failed = [n for n in resolved.nets if n.id in unrouted]
        rest = [n for n in order if n.id not in unrouted]
        rng.shuffle(rest)
        failed.sort(key=lambda n: _difficulty(n, pin_pos), reverse=True)
        return failed + rest
    shuffled = list(order)
    rng.shuffle(shuffled)
    return shuffled


def _add_forced_strips(board, instances, resolved, result: GlobalResult) -> None:
    """Give an unrouted net one strip per occupied row, covering that row's pins where free.

    Diagnostic only: keeps the independent validator pointing at connectivity rather than a
    missing strip, per notes section 6. Grouping same-row pins into one strip
    (rather than a strip per pin) avoids introducing overlap/gap artifacts among the net's
    own pins.
    """
    if not result.unrouted:
        return
    routing = result.routing
    pin_pos = pin_world_positions(instances)
    for net in resolved.nets:
        if net.id not in result.unrouted:
            continue
        obstacles = build_obstacles(instances, routing, resolved.pin_to_net, net.id)
        pins_by_row: dict[int, list[int]] = {}
        for ref in net.pins:
            x, y = pin_pos[ref]
            pins_by_row.setdefault(y, []).append(x)
        for y, xs in sorted(pins_by_row.items()):
            xa, xb = min(xs), max(xs)
            cells = [(x, y) for x in range(xa, xb + 1)]
            halo = [(cx, y) for cx in (xa - 1, xb + 1) if 1 <= cx <= board.w]
            if not any(obstacles.conductive.get(p) for p in cells + halo):
                routing.add_strip(Strip(y, xa, xb, net.id))
