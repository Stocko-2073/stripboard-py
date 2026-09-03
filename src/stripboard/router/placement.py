"""Phase 1 -- placement (spec section 7).

Move unlocked components (translate; optionally flip 180) to minimize a pre-routing cost:
a separable half-perimeter wirelength (HPWL) summed over all nets, plus a *congestion*
penalty that discourages parking a movable body (keep-out) in a corridor many other nets
must route through. Locked-component pins are fixed anchors.

    place_cost = Sum_nets w_net * [w_x*xspan + w_y*yspan]  +  w_cong * congestion(keep-outs)

HPWL alone is routability-blind: it will happily shave a unit of wirelength by dropping a
tall keep-out into the densest part of the board, which Phase 2 then cannot route around.
The congestion term is a cheap static proxy for that demand; the pipeline's place->route
retry loop (which tries these candidates best-first) is the actual feasibility guarantee.

Placement must stay *legal* -- every component on board and no cross-component pin/keep-out
overlaps -- because Phase 2 cannot repair component-fixed geometry (router-notes.md
section 2). Legality is enforced in the move generator, not merely minimized.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

from .geometry import Point
from .model import Board, ComponentInstance, Weights
from .netlist import ResolvedNetlist, pin_world_positions
from .rng import make_rng


class PlacementError(RuntimeError):
    """Raised when no legal placement of the unlocked components exists."""


@dataclass(frozen=True)
class PlacementOptions:
    sa_iterations: int = 4000
    sa_start_temp: float = 10.0
    sa_end_temp: float = 0.05
    brute_force_budget: int = 200_000  # max joint candidate combos to brute-force
    w_cong: float = 0.5  # weight of the congestion penalty relative to HPWL (0 disables)


# --------------------------------------------------------------------------- HPWL


def hpwl(instances: list[ComponentInstance], resolved: ResolvedNetlist, weights: Weights) -> float:
    """Separable half-perimeter wirelength summed over nets (spec section 7)."""
    pos = pin_world_positions(instances)
    total = 0.0
    for net in resolved.nets:
        pts = [pos[ref] for ref in net.pins if ref in pos]
        if len(pts) <= 1:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xspan = max(xs) - min(xs)
        yspan = max(ys) - min(ys)
        total += net.weight * (weights.w_x * xspan + weights.w_y * yspan)
    return total


# --------------------------------------------------------------------------- congestion


def congestion_field(
    instances: list[ComponentInstance], resolved: ResolvedNetlist
) -> dict[Point, float]:
    """Static routing-demand heat map from the *locked* pins of every net.

    Each net contributes ``net.weight`` of demand to every cell of the bounding box of its
    fixed anchors (its locked pins); nets with fewer than two locked pins have no span and
    are skipped. The field depends only on locked geometry, so it is computed once per
    placement search and the per-candidate penalty is an O(keep-out cells) lookup.

    A cell's value approximates how many nets' routes are forced to pass through it; sitting
    a movable keep-out on hot cells is what blocks Phase 2, so we price it in here.
    """
    locked_pos: dict[tuple[str, str], Point] = {}
    for inst in instances:
        if inst.locked:
            for lid, p in inst.world_pins().items():
                locked_pos[(inst.id, lid)] = p
    field: dict[Point, float] = {}
    for net in resolved.nets:
        pts = [locked_pos[ref] for ref in net.pins if ref in locked_pos]
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        for x in range(min(xs), max(xs) + 1):
            for y in range(min(ys), max(ys) + 1):
                field[(x, y)] = field.get((x, y), 0.0) + net.weight
    return field


def congestion_penalty(
    instances: list[ComponentInstance], field: dict[Point, float]
) -> float:
    """Total demand under the keep-outs of the *unlocked* components (locked ones are fixed
    and constant, so they never change the ranking)."""
    if not field:
        return 0.0
    total = 0.0
    for inst in instances:
        if inst.locked:
            continue
        for r in inst.world_keepouts():
            for p in r.points():
                total += field.get(p, 0.0)
    return total


def _place_cost(
    board: Board,
    placed: list[ComponentInstance],
    resolved: ResolvedNetlist,
    field: dict[Point, float],
    w_cong: float,
) -> float:
    """Combined placement objective: HPWL plus the weighted congestion penalty."""
    cost = hpwl(placed, resolved, board.weights)
    if w_cong and field:
        cost += w_cong * congestion_penalty(placed, field)
    return cost


# --------------------------------------------------------------------------- legality


def _on_board(board: Board, inst: ComponentInstance) -> bool:
    for p in inst.world_pins().values():
        if not board.in_bounds(p):
            return False
    for r in inst.world_keepouts():
        if not r.on_board(board.w, board.h):
            return False
    return True


def is_legal(board: Board, instances: list[ComponentInstance]) -> bool:
    """All components on board and no cross-component pin/keep-out overlaps."""
    pin_at: dict[Point, str] = {}
    ko_at: dict[Point, str] = {}
    for inst in instances:
        if not _on_board(board, inst):
            return False
        for p in inst.world_pins().values():
            if p in pin_at and pin_at[p] != inst.id:
                return False  # pin ∩ pin
            if p in ko_at and ko_at[p] != inst.id:
                return False  # pin ∩ keep-out
            pin_at[p] = inst.id
        for r in inst.world_keepouts():
            for p in r.points():
                if p in ko_at and ko_at[p] != inst.id:
                    return False  # keep-out ∩ keep-out
                if p in pin_at and pin_at[p] != inst.id:
                    return False  # keep-out ∩ pin
                ko_at[p] = inst.id
    return True


# --------------------------------------------------------------------------- candidates


def _on_board_candidates(board: Board, inst: ComponentInstance) -> list[tuple[Point, bool]]:
    """Every (origin, flipped) placing this instance entirely on board."""
    out: list[tuple[Point, bool]] = []
    for flipped in (False, True):
        for oy in range(1, board.h + 1):
            for ox in range(1, board.w + 1):
                cand = inst.moved((ox, oy), flipped)
                if _on_board(board, cand):
                    out.append(((ox, oy), flipped))
    return out


def _apply(
    base: list[ComponentInstance], choices: dict[str, tuple[Point, bool]]
) -> list[ComponentInstance]:
    out: list[ComponentInstance] = []
    for inst in base:
        if inst.id in choices:
            origin, flipped = choices[inst.id]
            out.append(inst.moved(origin, flipped))
        else:
            out.append(inst)
    return out


# --------------------------------------------------------------------------- search


def place(
    board: Board,
    instances: list[ComponentInstance],
    resolved: ResolvedNetlist,
    *,
    seed: int = 0,
    options: PlacementOptions | None = None,
) -> list[ComponentInstance]:
    """Return instances with unlocked components placed to minimize the placement cost.

    Convenience wrapper around :func:`place_candidates` returning only the best placement.
    """
    return place_candidates(board, instances, resolved, seed=seed, options=options, limit=1)[0]


def place_candidates(
    board: Board,
    instances: list[ComponentInstance],
    resolved: ResolvedNetlist,
    *,
    seed: int = 0,
    options: PlacementOptions | None = None,
    limit: int = 1,
) -> list[list[ComponentInstance]]:
    """Return up to ``limit`` legal placements, best (lowest placement cost) first.

    The pipeline routes these in order and keeps the first that yields a feasible layout, so
    the ranking is a *routability preference*, not a guarantee -- hence the congestion term
    in the cost, which pushes plausibly-unroutable placements down the list.
    """
    opts = options or PlacementOptions()
    limit = max(1, limit)
    unlocked = [i for i in instances if not i.locked]
    if not unlocked:
        if not is_legal(board, instances):
            raise PlacementError("Locked-only placement is illegal (fixed geometry overlaps).")
        return [list(instances)]

    cand_lists = {i.id: _on_board_candidates(board, i) for i in unlocked}
    for i in unlocked:
        if not cand_lists[i.id]:
            raise PlacementError(f"Component {i.id!r} has no on-board placement.")

    field = congestion_field(instances, resolved) if opts.w_cong else {}
    combos = math.prod(len(cand_lists[i.id]) for i in unlocked)
    if combos <= opts.brute_force_budget:
        ranked = _brute_force(board, instances, unlocked, cand_lists, resolved, field, opts, limit)
        if not ranked:
            raise PlacementError("No legal placement found (brute force).")
        return ranked
    return _anneal(board, instances, unlocked, cand_lists, resolved, field, seed, opts, limit)


def _brute_force(
    board, instances, unlocked, cand_lists, resolved, field, opts, limit
) -> list[list[ComponentInstance]]:
    ids = [i.id for i in unlocked]

    def legal_scored():
        for combo in itertools.product(*(cand_lists[i] for i in ids)):
            choices = dict(zip(ids, combo, strict=True))
            placed = _apply(instances, choices)
            if not is_legal(board, placed):
                continue
            cost = _place_cost(board, placed, resolved, field, opts.w_cong)
            # deterministic tie-break: lower origins, unflipped first (keys are unique per
            # combo, so nsmallest never has to compare the placements themselves).
            key = (cost, tuple((c[0][1], c[0][0], c[1]) for c in combo))
            yield (key, placed)

    # nsmallest keeps only the top `limit` placements in memory, not every legal combo.
    best = heapq.nsmallest(limit, legal_scored(), key=lambda t: t[0])
    return [placed for _, placed in best]


def _find_legal_start(
    board, instances, unlocked, cand_lists, rng
) -> list[ComponentInstance] | None:
    """Greedy sequential placement to a first legal configuration."""
    choices: dict[str, tuple[Point, bool]] = {}
    placed_so_far = [i for i in instances if i.locked]
    for inst in unlocked:
        cands = list(cand_lists[inst.id])
        rng.shuffle(cands)
        ok = False
        for origin, flipped in cands:
            trial = placed_so_far + [inst.moved(origin, flipped)]
            if is_legal(board, trial):
                choices[inst.id] = (origin, flipped)
                placed_so_far = trial
                ok = True
                break
        if not ok:
            return None
    result = _apply(instances, choices)
    return result if is_legal(board, result) else None


def _anneal(
    board, instances, unlocked, cand_lists, resolved, field, seed, opts, limit
) -> list[list[ComponentInstance]]:
    rng = make_rng(seed)
    current = _find_legal_start(board, instances, unlocked, cand_lists, rng)
    if current is None:
        raise PlacementError("No legal placement found (annealing start).")

    def cost_of(placed):
        return _place_cost(board, placed, resolved, field, opts.w_cong)

    # Keep the best-scoring distinct configuration seen, keyed on the unlocked placements, so
    # place_candidates can hand the pipeline several genuinely different placements to try.
    pool: dict[tuple, tuple[float, list[ComponentInstance]]] = {}

    def remember(placed, cost):
        key = tuple((i.id, i.origin, i.flipped) for i in placed if i.id in cand_lists)
        prior = pool.get(key)
        if prior is None or cost < prior[0]:
            pool[key] = (cost, placed)

    cur_cost = cost_of(current)
    remember(current, cur_cost)
    ids = [i.id for i in unlocked]
    n = opts.sa_iterations
    for step in range(n):
        t = opts.sa_start_temp * (opts.sa_end_temp / opts.sa_start_temp) ** (step / max(1, n - 1))
        move_id = ids[rng.randrange(len(ids))]
        origin, flipped = cand_lists[move_id][rng.randrange(len(cand_lists[move_id]))]
        trial_choices = {move_id: (origin, flipped)}
        # rebuild from current placements
        cur_choices = {
            inst.id: (inst.origin, inst.flipped) for inst in current if inst.id in cand_lists
        }
        cur_choices.update(trial_choices)
        trial = _apply(instances, cur_choices)
        if not is_legal(board, trial):
            continue
        trial_cost = cost_of(trial)
        remember(trial, trial_cost)
        delta = trial_cost - cur_cost
        if delta <= 0 or rng.random() < math.exp(-delta / max(t, 1e-9)):
            current, cur_cost = trial, trial_cost
    ranked = sorted(pool.values(), key=lambda t: t[0])
    return [placed for _, placed in ranked[:limit]]
