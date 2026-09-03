"""Phase 2c -- strip-extent cut minimization.

The cut count doesn't decompose into per-edge costs: it depends on the final strip extents
and on *sharing* a cut column between same-row strips. So, with topology fixed, we run a
separate per-row pass. Extending a strip past its pins never changes the electrical
diameter (spec section 4.3 corollary), so copper is free to trade for fewer cuts.

Per row, the strips (all of distinct nets -- the router makes one strip per net per row)
are laid out so that:

* the outermost strips reach the board edge, so their outer cuts fall off board (no cut);
* each interior boundary uses a gap of exactly one column, so the left strip's right cut
  and the right strip's left cut land on the *same* column and collapse to one cut.

Extension is clamped by **foreign conductive** cells -- pins or jumper endpoints on the row
that are not themselves on a strip (e.g. an unrouted net's pins). A strip may never cover
such a cell (cross-net collision) nor place its edge cut on one (spec section 3.1/5); other
strips are handled by the coordination above.
"""

from __future__ import annotations

from ..geometry import Point
from ..model import Board, ComponentInstance, Routing, Strip


def minimize_cuts(
    board: Board, routing: Routing, instances: list[ComponentInstance] | None = None
) -> Routing:
    """Return a new Routing with strips extended to minimize distinct physical cuts."""
    instances = instances or []
    out = Routing()
    for j in routing.all_jumpers():
        out.add_jumper(j)

    # Conductive cells that a strip must not extend over or cut on: pins and jumper endpoints.
    all_conductive: set[Point] = set()
    for inst in instances:
        all_conductive.update(inst.world_pins().values())
    for jm in routing.all_jumpers():
        all_conductive.update(jm.endpoints())

    by_row: dict[int, list[Strip]] = {}
    for s in routing.all_strips():
        by_row.setdefault(s.y, []).append(s)

    for y, strips in by_row.items():
        ordered = sorted(strips, key=lambda s: (s.xa, s.xb))
        n = len(ordered)
        strip_cols = {x for s in ordered for x in range(s.xa, s.xb + 1)}
        # foreign conductive columns on this row that no strip covers
        floating = sorted(x for (x, yy) in all_conductive if yy == y and x not in strip_cols)

        for i, s in enumerate(ordered):
            # left edge: extend the leftmost strip to the board edge; keep interior lefts
            if i == 0:
                new_xa = 1
                left = [f for f in floating if f < s.xa]
                if left:
                    new_xa = max(new_xa, max(left) + 2)
            else:
                new_xa = s.xa
            new_xa = min(new_xa, s.xa)

            # right edge: fill toward the next strip (shared cut) or the board edge
            target = board.w if i == n - 1 else ordered[i + 1].xa - 2
            right = [f for f in floating if f > s.xb]
            if right:
                target = min(target, min(right) - 2)
            new_xb = max(s.xb, target)

            out.add_strip(Strip(y, new_xa, new_xb, s.net_id))
    return out
