"""Top-level orchestration: :func:`route`.

    resolve netlist -> legal placement (Phase 1) -> per-net routing with rip-up/reroute
    (Phase 2a/2b) -> strip-extent cut minimization (Phase 2c) -> validate + cost -> Result.

Input errors (``NetlistError``) and placement infeasibility (``PlacementError``) raise;
routing infeasibility is reported in the :class:`Result` (or raises if requested).
"""

from __future__ import annotations

from .cost import compute_cost
from .cuts import physical_cuts
from .model import Board, ComponentInstance, Net, Weights
from .netlist import resolve
from .placement import place_candidates
from .result import (
    NetStatus,
    Placement,
    Result,
    RouteOptions,
    RouteStatus,
    RoutingInfeasibleError,
)
from .routing.ripup import route_nets
from .routing.strip_extent import minimize_cuts
from .validation import validate


def route(
    board: Board,
    instances: list[ComponentInstance],
    netlist: list[Net],
    *,
    weights: Weights | None = None,
    seed: int = 0,
    options: RouteOptions | None = None,
) -> Result:
    """Compute a stripboard layout for ``instances`` + ``netlist`` on ``board``."""
    opts = options or RouteOptions()

    resolved = resolve(instances, netlist)  # NetlistError on bad input
    # Phase 1 gives a routability-ranked list of legal placements; Phase 2 routes them
    # best-first and we keep the first that is fully feasible (or the best partial). This
    # closes the place->route gap: a wirelength-optimal but unroutable placement no longer
    # sinks the whole solve when a slightly-costlier routable one exists.
    candidates = place_candidates(  # PlacementError if none legal
        board, instances, resolved, seed=seed, options=opts.placement,
        limit=max(1, opts.max_placement_attempts),
    )

    best: tuple | None = None  # (key, placed, routing, gr, validation, cost, status)
    for placed in candidates:
        gr = route_nets(board, placed, resolved, seed=seed, weights=weights, options=opts.ripup)
        routing = minimize_cuts(board, gr.routing, placed)
        validation = validate(board, placed, netlist, routing)
        cost = compute_cost(board, placed, netlist, routing, weights=weights)

        if not gr.unrouted and validation.ok:
            status = RouteStatus.FEASIBLE
        elif gr.routed:
            status = RouteStatus.PARTIAL
        else:
            status = RouteStatus.INFEASIBLE

        # Prefer more routed nets, then a valid layout, then lower cost. Candidates are
        # already placement-cost-ordered, so ties keep the earlier (cheaper) placement.
        key = (len(gr.routed), validation.ok, -cost.total)
        if best is None or key > best[0]:
            best = (key, placed, routing, gr, validation, cost, status)
        if status is RouteStatus.FEASIBLE:
            break

    assert best is not None  # candidates is non-empty
    _, placed, routing, gr, validation, cost, status = best

    if opts.on_infeasible == "raise" and status is not RouteStatus.FEASIBLE:
        raise RoutingInfeasibleError(
            f"routing not feasible: status={status.value}, unrouted={sorted(gr.unrouted)}, "
            f"validation={validation.summary()}"
        )

    placements = [Placement(i.id, i.origin, i.flipped) for i in placed]
    net_status = [
        NetStatus(n.id, n.id not in gr.unrouted, gr.unrouted.get(n.id)) for n in resolved.nets
    ]
    return Result(
        status=status,
        placements=placements,
        routing=routing,
        physical_cuts=physical_cuts(routing.all_strips(), board.w, board.h),
        validation=validation,
        cost=cost,
        net_status=net_status,
        seed=seed,
    )
