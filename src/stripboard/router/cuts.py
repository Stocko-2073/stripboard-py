"""Cuts, derived from strips (spec section 5).

A cut is never a stored entity: it is the on-board point immediately past a strip's edge.
The physical cut set is the union of every strip's edge cuts with coincident positions
collapsed to one -- a cut shared by two same-row strips is a single piece of physical work.
"""

from __future__ import annotations

from collections.abc import Iterable

from .geometry import Point
from .model import Strip


def strip_cuts(strip: Strip, w: int, h: int) -> set[Point]:
    """On-board cut points for a single strip (spec section 5)."""
    return strip.edge_cuts(w, h)


def physical_cuts(strips: Iterable[Strip], w: int, h: int) -> set[Point]:
    """Distinct physical cut positions across all strips (spec section 5, output collapse).

    The set naturally dedupes coincident cuts, so ``len(physical_cuts(...))`` is the
    distinct-cut count used by the routing cost (spec section 7).
    """
    out: set[Point] = set()
    for s in strips:
        out |= s.edge_cuts(w, h)
    return out
