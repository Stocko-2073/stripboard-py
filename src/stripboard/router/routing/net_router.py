"""Phase 2a -- per-net routing.

The geometry makes this tractable: a pin's strip is forced onto the pin's own row. So a
net becomes one horizontal strip per occupied row, and those row-strips are joined into a
**spanning tree over the row-nodes** by vertical jumpers (each jumper a single column that
can bridge far-apart rows in one hop, arcing over intermediate rows). A tree over ``k``
occupied rows always has ``k - 1`` edges, so the **jumper count is fixed** for a net; the only
levers are the tree *shape* and each jumper's *column*.

For each net we:

1. enumerate candidate topologies -- **all** spanning trees for small nets (Pruefer decode),
   a curated diverse set (chain + stars + double-stars) for the rare high-fan-out net;
2. for each topology, solve the jumper columns with a **branch-and-bound backtracking search**
   over the full-board-width feasible column set per edge (forward-checking on same-net jumper
   overlap, most-constrained-variable ordering, a monotone electrical-diameter lower bound, and
   a node budget), sharing one incumbent cost across topologies.

The per-net objective is the part of spec section 7 this phase owns: the **weighted electrical
diameter** ``w_len * net.weight * netLength``. Jumper count is constant (``w_jmp * (k-1)``) and
**cuts are deferred to Phase 2c** (``strip_extent.minimize_cuts`` extends each row's single
strip independently of the pre-extension jumper column, so counting pre-extension cuts here
only biased the search -- spec section 4.3 corollary).
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from ..geometry import Point
from ..model import Board, Jumper, PinRef, Strip, Weights
from ..netgraph import net_length
from ..netlist import ResolvedNet
from ..occupancy import OccupancyIndex

# Result of routing a single net: its strips and jumpers.
NetRouting = tuple[list[Strip], list[Jumper]]

# Tuning knobs (bounded effort; NOTES section 2 sanctions a bounded search budget).
_DOMAIN_CAP = 20_000  # per-topology full-width column product above which domains go compact
_NODE_BUDGET = 50_000  # per-net cap on DFS node expansions (safety valve -> best-effort)
_MAX_CURATED = 64  # cap on the curated topology set for high-fan-out nets
_MAX_STEINER_ROWS = 6  # candidate empty detour rows tried when the fixed-topology search fails


class Congestion:
    """Interface for negotiated-congestion penalties (Phase 2b). Default: none."""

    def extra(self, strips: Iterable[Strip], jumpers: Iterable[Jumper]) -> float:
        return 0.0


# --------------------------------------------------------------------------- validity


def _strip_covers_foreign(y: int, xa: int, xb: int, obstacles: OccupancyIndex) -> bool:
    """A strip cell lands on a foreign conductive point. Monotone in the strip extent."""
    for x in range(xa, xb + 1):
        if obstacles.conductive.get((x, y)):
            return True
    return False


def _strip_cut_conflicts(y: int, xa: int, xb: int, obstacles: OccupancyIndex, board: Board) -> bool:
    """The strip's edge-cut columns land on a foreign conductive point (SPEC 3.3 / rule 9).

    Not monotone in the extent (the cut columns move as the strip grows), so this is checked
    only once a strip's extent is final. A cut may sit under a jumper arc (clearance), so only
    conductive occupancy is disqualifying.
    """
    for cx in (xa - 1, xb + 1):
        if 1 <= cx <= board.w and 1 <= y <= board.h and obstacles.conductive.get((cx, y)):
            return True
    return False


def _strip_conflicts(strip: Strip, obstacles: OccupancyIndex, board: Board) -> bool:
    # A strip may cross clearance (keep-outs, foreign arcs) but not any foreign conductive
    # point, and its edge-cut columns must be free of foreign conductive.
    return _strip_covers_foreign(strip.y, strip.xa, strip.xb, obstacles) or _strip_cut_conflicts(
        strip.y, strip.xa, strip.xb, obstacles, board
    )


def _jumper_conflicts(j: Jumper, obstacles: OccupancyIndex, own_pins: set[Point]) -> bool:
    for ep in j.endpoints():
        if obstacles.conductive.get(ep):
            return True  # endpoint on foreign conductive point
        if obstacles.clearance.get(ep):
            return True  # endpoint on a keep-out or a foreign jumper's arc (jumper∩keepout/jumper)
        if ep in own_pins:
            return True  # pin ∩ jumper endpoint (forbidden even same net)
    for p in j.keepout():
        if p in own_pins:
            return True  # arc over a pin (forbidden even same net)
        for occ in obstacles.conductive.get(p, ()):
            if occ.kind in ("pin", "jumper_end"):
                return True  # arc over foreign pin/endpoint (strips are allowed)
        if obstacles.clearance.get(p):
            return True  # arc over a keep-out or another jumper's arc
    return False


def _self_consistent(jumpers: list[Jumper]) -> bool:
    seen: set[Point] = set()
    for j in jumpers:
        pts = set(j.endpoints()) | j.keepout()
        if pts & seen:
            return False  # two of this net's jumpers overlap
        seen |= pts
    return True


def _candidate_valid(
    strips: list[Strip],
    jumpers: list[Jumper],
    obstacles: OccupancyIndex,
    own_pins: set[Point],
    board: Board,
) -> bool:
    if not _self_consistent(jumpers):
        return False
    for s in strips:
        if _strip_conflicts(s, obstacles, board):
            return False
    for j in jumpers:
        if _jumper_conflicts(j, obstacles, own_pins):
            return False
    return True


# --------------------------------------------------------------------------- cost


def _candidate_cost(
    strips: list[Strip],
    jumpers: list[Jumper],
    pins: list[PinRef],
    pin_pos: dict[PinRef, Point],
    internal_pairs: list[tuple[PinRef, PinRef]],
    net_weight: float,
    weights: Weights,
    congestion: Congestion | None,
) -> float:
    # spec section 7, the part this phase owns: weighted electrical diameter + the (constant)
    # jumper term. Cuts are Phase 2c's responsibility (see module docstring), so no cut term.
    nl = net_length(pins, pin_pos, strips, jumpers, internal_pairs)
    base = weights.w_len * net_weight * nl + weights.w_jmp * len(jumpers)
    if congestion is not None:
        base += congestion.extra(strips, jumpers)
    return base


def _tiebreak_key(strips: list[Strip], jumpers: list[Jumper]) -> tuple:
    return (
        tuple(sorted((s.y, s.xa, s.xb) for s in strips)),
        tuple(sorted((j.x, j.ya, j.yb) for j in jumpers)),
    )


# --------------------------------------------------------------------------- topology


def _prufer_decode(seq: list[int], k: int) -> list[tuple[int, int]]:
    """Decode a Pruefer sequence (labels 0..k-1, length k-2) into a spanning tree's edges."""
    degree = [1] * k
    for x in seq:
        degree[x] += 1
    edges: list[tuple[int, int]] = []
    for x in seq:
        for leaf in range(k):
            if degree[leaf] == 1:
                edges.append((leaf, x) if leaf < x else (x, leaf))
                degree[leaf] -= 1
                degree[x] -= 1
                break
    rest = [i for i in range(k) if degree[i] == 1]
    a, b = rest[0], rest[1]
    edges.append((a, b) if a < b else (b, a))
    return edges


def _spanning_trees(k: int) -> list[list[tuple[int, int]]]:
    """Every spanning tree over ``k`` row-nodes (k^(k-2) of them), deterministic order."""
    if k <= 2:
        return [[(0, 1)]] if k == 2 else [[]]
    return [_prufer_decode(list(seq), k) for seq in itertools.product(range(k), repeat=k - 2)]


def _curated_trees(k: int) -> list[list[tuple[int, int]]]:
    """A diverse, deterministic set for high-fan-out nets: chain + stars + double-stars."""
    trees: list[list[tuple[int, int]]] = []
    seen: set[tuple[tuple[int, int], ...]] = set()

    def add(edges: list[tuple[int, int]]) -> None:
        norm = tuple(sorted((min(a, b), max(a, b)) for a, b in edges))
        if len(norm) == k - 1 and norm not in seen:
            seen.add(norm)
            trees.append([(min(a, b), max(a, b)) for a, b in edges])

    add([(i, i + 1) for i in range(k - 1)])  # chain (feasibility baseline)
    for hub in range(k):  # a star per hub (central hubs minimize diameter)
        add([(hub, i) for i in range(k) if i != hub])
    for split in range(1, k - 1):  # double-stars (balance diameter vs. feasibility)
        left, right = list(range(split)), list(range(split, k))
        hub_l, hub_r = left[len(left) // 2], right[len(right) // 2]
        edges = (
            [(hub_l, i) for i in left if i != hub_l]
            + [(hub_r, i) for i in right if i != hub_r]
            + [(hub_l, hub_r)]
        )
        add(edges)
    return trees[:_MAX_CURATED]


def _build_candidate(
    rows: list[int],
    pins_by_row: dict[int, list[int]],
    edges: list[tuple[int, int]],
    columns: tuple[int, ...],
    net_id: str,
) -> NetRouting:
    reqs: dict[int, set[int]] = {i: set(pins_by_row[rows[i]]) for i in range(len(rows))}
    jumpers: list[Jumper] = []
    for (i, j), c in zip(edges, columns, strict=True):
        reqs[i].add(c)
        reqs[j].add(c)
        ya, yb = sorted((rows[i], rows[j]))
        jumpers.append(Jumper(c, ya, yb, net_id))
    strips = [Strip(rows[i], min(reqs[i]), max(reqs[i]), net_id) for i in range(len(rows))]
    return strips, jumpers


# --------------------------------------------------------------------------- top level


def route_net(
    board: Board,
    net: ResolvedNet,
    pin_pos: dict[PinRef, Point],
    internal_pairs: list[tuple[PinRef, PinRef]],
    obstacles: OccupancyIndex,
    *,
    weights: Weights | None = None,
    congestion: Congestion | None = None,
) -> NetRouting | None:
    """Route one net; return (strips, jumpers), or ``None`` if it cannot be routed."""
    w = weights if weights is not None else board.weights
    pins = sorted(net.pins)
    if not pins:
        return ([], [])

    own_pins = {pin_pos[r] for r in pins}
    pins_by_row: dict[int, list[int]] = {}
    for ref in pins:
        x, y = pin_pos[ref]
        pins_by_row.setdefault(y, []).append(x)
    rows = sorted(pins_by_row)
    net_pairs = [(a, b) for (a, b) in internal_pairs if a in net.pins and b in net.pins]

    # Single row (or all pins internally common on one row): one strip, no jumper.
    if len(rows) == 1:
        y = rows[0]
        strip = Strip(y, min(pins_by_row[y]), max(pins_by_row[y]), net.id)
        if _candidate_valid([strip], [], obstacles, own_pins, board):
            return ([strip], [])
        return None

    ctx = _Ctx(
        board, net, rows, pins_by_row, pins, pin_pos, net_pairs, obstacles, own_pins, w, congestion
    )
    result = _route_all_topologies(ctx)
    if result is not None:
        return result
    # Boxed-in net: the pin rows alone admit no legal route. Retry allowing one empty detour
    # ("Steiner") row -- a strip past the blocking pins, reached by an extra jumper.
    return _route_steiner_fallback(ctx)


@dataclass
class _Ctx:
    """Bundle of per-net routing context, to keep helper signatures short."""

    board: Board
    net: ResolvedNet
    rows: list[int]
    pins_by_row: dict[int, list[int]]
    pins: list[PinRef]
    pin_pos: dict[PinRef, Point]
    net_pairs: list[tuple[PinRef, PinRef]]
    obstacles: OccupancyIndex
    own_pins: set[Point]
    weights: Weights
    congestion: Congestion | None


@dataclass
class _TopoInfo:
    """Precomputed per-topology data for the electrical-diameter lower bound."""

    edges: list[tuple[int, int]]
    paths: dict[tuple[int, int], list[int]]  # (a<b) -> ordered edge indices from a to b
    vert: dict[tuple[int, int], float]  # (a<b) -> sum of jumper vlengths on that path
    xmin: list[int]  # per row-index, min pin column (0 for a pin-less Steiner row)
    xmax: list[int]  # per row-index, max pin column (0 for a pin-less Steiner row)
    intra: float  # max intra-row pin span (a constant floor on the diameter)
    steiner: frozenset[int]  # row-indices with no pins (empty detour rows); usually empty


def _topo_info(ctx: _Ctx, edges: list[tuple[int, int]]) -> _TopoInfo:
    rows, pbr = ctx.rows, ctx.pins_by_row
    k = len(rows)
    steiner = frozenset(i for i in range(k) if not pbr[rows[i]])
    xmin = [min(pbr[rows[i]]) if pbr[rows[i]] else 0 for i in range(k)]
    xmax = [max(pbr[rows[i]]) if pbr[rows[i]] else 0 for i in range(k)]
    intra = float(max((xmax[i] - xmin[i] for i in range(k) if i not in steiner), default=0.0))
    edge_vlen = [abs(rows[i] - rows[j]) for (i, j) in edges]
    adj: list[list[tuple[int, int]]] = [[] for _ in range(k)]
    for ei, (i, j) in enumerate(edges):
        adj[i].append((j, ei))
        adj[j].append((i, ei))

    paths: dict[tuple[int, int], list[int]] = {}
    vert: dict[tuple[int, int], float] = {}
    for a in range(k):
        parent: dict[int, tuple[int, int]] = {a: (-1, -1)}
        dq = deque([a])
        while dq:
            u = dq.popleft()
            for v, ei in adj[u]:
                if v not in parent:
                    parent[v] = (u, ei)
                    dq.append(v)
        for b in range(a + 1, k):
            pe: list[int] = []
            vsum = 0.0
            cur = b
            while cur != a:
                p, ei = parent[cur]
                pe.append(ei)
                vsum += edge_vlen[ei]
                cur = p
            pe.reverse()  # order from a to b
            paths[(a, b)] = pe
            vert[(a, b)] = vsum
    return _TopoInfo(edges, paths, vert, xmin, xmax, intra, steiner)


def _diameter_lb(info: _TopoInfo, assigned: dict[int, int]) -> float:
    """Monotone lower bound on the electrical diameter for a partial column assignment.

    dist(p,q) = VERT(a,b) + TV([x_p, waypoint columns, x_q]); dropping unassigned waypoints only
    lowers the total variation, so this never exceeds any completion's diameter and only grows as
    columns are assigned. Valid only without internal ties (weight-0 shortcuts break the metric).
    """
    xmin, xmax = info.xmin, info.xmax
    best = info.intra
    for (a, b), pe in info.paths.items():
        if a in info.steiner or b in info.steiner:
            continue  # only real pin pairs bound the electrical diameter; a Steiner node has
            # no pin span (its jumper columns still count as waypoints on pin-to-pin paths)
        wp = [assigned[e] for e in pe if e in assigned]
        va = info.vert[(a, b)]
        if wp:
            tv_wp = sum(abs(wp[t + 1] - wp[t]) for t in range(len(wp) - 1))
            w0, wl = wp[0], wp[-1]
            local = max(
                abs(w0 - xp) + tv_wp + abs(xq - wl)
                for xp in (xmin[a], xmax[a])
                for xq in (xmin[b], xmax[b])
            )
        else:
            local = max(abs(xq - xp) for xp in (xmin[a], xmax[a]) for xq in (xmin[b], xmax[b]))
        best = max(best, va + local)
    return best


def feasible_columns(
    board: Board,
    net_id: str,
    ya: int,
    yb: int,
    obstacles: OccupancyIndex,
    own_pins: set[Point],
) -> list[int]:
    """Every board column where a jumper (ya,yb) is collision-free (SPEC/NOTES section 2)."""
    return [
        c
        for c in range(1, board.w + 1)
        if not _jumper_conflicts(Jumper(c, ya, yb, net_id), obstacles, own_pins)
    ]


def _feasible_columns(ctx: _Ctx, ya: int, yb: int) -> list[int]:
    return feasible_columns(ctx.board, ctx.net.id, ya, yb, ctx.obstacles, ctx.own_pins)


def _route_all_topologies(ctx: _Ctx, budget: list[int] | None = None) -> NetRouting | None:
    rows = ctx.rows
    k = len(rows)
    m = k - 1  # jumpers
    # A caller (the Steiner fallback) may pass a shared budget to cap total work across several
    # augmented searches; otherwise we own a fresh budget and refill it for the full-width pass.
    owns_budget = budget is None

    # Full-width feasible columns per row-pair (memoised; reused across every topology).
    fpair: dict[tuple[int, int], list[int]] = {}
    for i in range(k):
        for j in range(i + 1, k):
            fpair[(i, j)] = _feasible_columns(ctx, rows[i], rows[j])

    topos = _spanning_trees(k) if k <= 5 else _curated_trees(k)

    # Screen and order topologies by their root lower bound (best-first); share the incumbent.
    entries: list[tuple[float, tuple, list[tuple[int, int]], _TopoInfo]] = []
    for edges in topos:
        info = _topo_info(ctx, edges)
        root_lb = _objective_lb(ctx, info, {}, m)
        entries.append((root_lb, tuple(sorted(edges)), edges, info))
    entries.sort(key=lambda e: (e[0], e[1]))

    # Compact (pin-aligned) columns keep the search small on wide-open boards; the diameter
    # optimum is pin-aligned there. Escalate to full width only if nothing routes.
    pin_xs = {x for xs in ctx.pins_by_row.values() for x in xs}
    compact_cols = {
        max(1, min(ctx.board.w, x + d)) for x in pin_xs for d in (-1, 0, 1)
    }

    best: tuple[float, tuple, list[Strip], list[Jumper]] | None = None
    used_compact = False
    if owns_budget:
        budget = [_NODE_BUDGET]
    assert budget is not None
    for root_lb, _, edges, info in entries:
        if best is not None and root_lb >= best[0]:
            break  # sorted ascending -> no later topology can improve on the incumbent
        domains, compact = _domains(fpair, edges, compact_cols)
        used_compact = used_compact or compact
        best = _search_topology(ctx, edges, info, domains, m, best, budget)
        if budget[0] < 0:
            break

    # Escalation: a wide-open confined net whose only legal columns fell outside the compact set.
    if best is None and used_compact:
        if owns_budget:
            budget = [_NODE_BUDGET]
        for _root_lb, _, edges, info in entries:
            domains = {ei: list(fpair[e]) for ei, e in enumerate(edges)}
            best = _search_topology(ctx, edges, info, domains, m, best, budget)
            if best is not None or budget[0] < 0:
                break

    return (best[2], best[3]) if best is not None else None


def steiner_row_candidates(board_h: int, rows: list[int]) -> list[int]:
    """Empty rows to try as a detour, nearest-first to the net's pin-row span (interior gaps
    first, then outward). Capped so the fallback stays bounded."""
    occupied = set(rows)
    lo, hi = rows[0], rows[-1]

    def key(r: int) -> tuple[int, int]:
        dist = 0 if lo <= r <= hi else min(abs(r - lo), abs(r - hi))
        return (dist, r)  # total order -> deterministic candidate list

    cands = [r for r in range(1, board_h + 1) if r not in occupied]
    cands.sort(key=key)
    return cands[:_MAX_STEINER_ROWS]


def _steiner_row_candidates(ctx: _Ctx) -> list[int]:
    return steiner_row_candidates(ctx.board.h, ctx.rows)


def _route_steiner_fallback(ctx: _Ctx) -> NetRouting | None:
    """Retry a boxed-in net allowing ONE empty detour ("Steiner") row: route down to a spare
    strip past the blocking pins, across, and back up -- one extra jumper. Each candidate row is
    an extra pin-less node in the spanning tree; we reuse the ordinary topology search on the
    augmented row set and keep the cheapest valid route. Only invoked on primary failure."""
    budget = [_NODE_BUDGET]  # one shared cap across all candidate searches
    best: tuple[float, tuple, list[Strip], list[Jumper]] | None = None
    for r in _steiner_row_candidates(ctx):
        aug_pbr = dict(ctx.pins_by_row)  # copy -- never mutate ctx.pins_by_row
        aug_pbr[r] = []
        aug = _Ctx(
            ctx.board, ctx.net, sorted(aug_pbr), aug_pbr, ctx.pins, ctx.pin_pos,
            ctx.net_pairs, ctx.obstacles, ctx.own_pins, ctx.weights, ctx.congestion,
        )
        res = _route_all_topologies(aug, budget)
        if res is not None:
            strips, jumpers = res
            cost = _candidate_cost(
                strips, jumpers, ctx.pins, ctx.pin_pos, ctx.net_pairs,
                ctx.net.weight, ctx.weights, ctx.congestion,
            )
            rank = (cost, _tiebreak_key(strips, jumpers))
            if best is None or rank < (best[0], best[1]):
                best = (cost, rank[1], strips, jumpers)
        if budget[0] < 0:
            break
    return (best[2], best[3]) if best is not None else None


def _domains(
    fpair: dict[tuple[int, int], list[int]],
    edges: list[tuple[int, int]],
    compact_cols: set[int],
) -> tuple[dict[int, list[int]], bool]:
    """Per-edge column domains; compact (pin-aligned) if the full-width product is too large."""
    product = 1
    for e in edges:
        product *= max(1, len(fpair[e]))
        if product > _DOMAIN_CAP:
            break
    if product <= _DOMAIN_CAP:
        return {ei: list(fpair[e]) for ei, e in enumerate(edges)}, False
    return {ei: [c for c in fpair[e] if c in compact_cols] for ei, e in enumerate(edges)}, True


def _objective_lb(ctx: _Ctx, info: _TopoInfo, assigned: dict[int, int], m: int) -> float:
    diam_lb = 0.0 if ctx.net_pairs else _diameter_lb(info, assigned)
    return ctx.weights.w_len * ctx.net.weight * diam_lb + ctx.weights.w_jmp * m


def _search_topology(
    ctx: _Ctx,
    edges: list[tuple[int, int]],
    info: _TopoInfo,
    domains: dict[int, list[int]],
    m: int,
    incumbent: tuple[float, tuple, list[Strip], list[Jumper]] | None,
    budget: list[int],
) -> tuple[float, tuple, list[Strip], list[Jumper]] | None:
    """Branch-and-bound over jumper columns for one fixed topology. Returns the best routing
    found (this topology's or the passed-in incumbent), or ``None`` if neither routes."""
    rows = ctx.rows
    edge_rows = edges  # (i, j) row indices, i < j
    edge_seg = [(rows[i], rows[j]) for (i, j) in edges]  # (ya, yb), ya < yb
    # Value-ordering center: midpoint of the two endpoint rows' pins (central-first -> low TV).
    centers: list[float] = []
    for i, j in edges:
        xs = ctx.pins_by_row[rows[i]] + ctx.pins_by_row[rows[j]]
        centers.append((min(xs) + max(xs)) / 2.0)
    remaining0 = [0] * len(rows)
    for i, j in edges:
        remaining0[i] += 1
        remaining0[j] += 1

    best = incumbent

    def dfs(
        assigned: dict[int, int],
        dom: dict[int, list[int]],
        reqs: list[set[int]],
        remaining: list[int],
    ) -> None:
        nonlocal best
        budget[0] -= 1
        if budget[0] < 0:
            return
        if len(assigned) == m:
            columns = tuple(assigned[e] for e in range(m))
            strips, jumpers = _build_candidate(rows, ctx.pins_by_row, edges, columns, ctx.net.id)
            if not _candidate_valid(strips, jumpers, ctx.obstacles, ctx.own_pins, ctx.board):
                return
            cost = _candidate_cost(
                strips, jumpers, ctx.pins, ctx.pin_pos, ctx.net_pairs,
                ctx.net.weight, ctx.weights, ctx.congestion,
            )
            rank = (cost, _tiebreak_key(strips, jumpers))
            if best is None or rank < (best[0], best[1]):
                best = (cost, rank[1], strips, jumpers)
            return
        # bound: prune when no completion can improve on the incumbent cost. Uses '>=' so
        # equal-cost branches are cut once the optimum is found -- on an open board many column
        # assignments share the minimum diameter and exploring them all is the blow-up to avoid.
        # The first optimal leaf reached (central-column-first) is kept, deterministically.
        if best is not None and _objective_lb(ctx, info, assigned, m) >= best[0]:
            return
        # most-constrained-variable: fewest live columns first (tie: longer jumper, then index)
        ei = min(
            (e for e in range(m) if e not in assigned),
            key=lambda e: (len(dom[e]), -abs(edge_seg[e][1] - edge_seg[e][0]), e),
        )
        i, j = edge_rows[ei]
        for c in sorted(dom[ei], key=lambda c: (abs(c - centers[ei]), c)):
            new_i, new_j = reqs[i] | {c}, reqs[j] | {c}
            # eager, monotone strip check
            if _strip_covers_foreign(rows[i], min(new_i), max(new_i), ctx.obstacles):
                continue
            if _strip_covers_foreign(rows[j], min(new_j), max(new_j), ctx.obstacles):
                continue
            # deferred exact check on a row whose extent is now final (edge cuts aren't monotone)
            rem_i, rem_j = remaining[i] - 1, remaining[j] - 1
            if rem_i == 0 and _strip_cut_conflicts(
                rows[i], min(new_i), max(new_i), ctx.obstacles, ctx.board
            ):
                continue
            if rem_j == 0 and _strip_cut_conflicts(
                rows[j], min(new_j), max(new_j), ctx.obstacles, ctx.board
            ):
                continue
            # forward-check: drop c from unassigned edges whose vertical span overlaps this one
            new_dom = _forward_check(dom, ei, c, edge_seg, assigned)
            if new_dom is None:
                continue
            assigned[ei] = c
            reqs2 = list(reqs)
            reqs2[i], reqs2[j] = new_i, new_j
            rem2 = list(remaining)
            rem2[i], rem2[j] = rem_i, rem_j
            dfs(assigned, new_dom, reqs2, rem2)
            del assigned[ei]
            if budget[0] < 0:
                return

    reqs0 = [set(ctx.pins_by_row[rows[i]]) for i in range(len(rows))]
    dfs({}, domains, reqs0, remaining0)
    return best


def _forward_check(
    dom: dict[int, list[int]],
    ei: int,
    c: int,
    edge_seg: list[tuple[int, int]],
    assigned: dict[int, int],
) -> dict[int, list[int]] | None:
    """Return domains with column ``c`` removed from every unassigned edge that would collide
    with edge ``ei`` at column ``c`` (overlapping vertical span). ``None`` if a domain empties."""
    ya, yb = edge_seg[ei]
    new_dom = {e: list(d) for e, d in dom.items()}
    for e, d in new_dom.items():
        if e == ei or e in assigned:
            continue
        ya2, yb2 = edge_seg[e]
        if max(ya, ya2) <= min(yb, yb2) and c in d:  # segments overlap -> same column collides
            d.remove(c)
            if not d:
                return None
    return new_dom
