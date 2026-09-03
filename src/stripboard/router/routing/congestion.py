"""Negotiated-congestion penalties (PathFinder-style), used to spread nets apart.

Collisions themselves are hard constraints enforced by the obstacle index; congestion is a
*soft* bias layered on top: cells that have been contended in earlier rip-up iterations
accrue a history cost, so among otherwise-equal valid routes the router prefers the ones
that leave contested resources free for other nets. Conflict *resolution* is driven mainly
by net reordering in :mod:`stripboard.router.routing.ripup`; congestion is the tie-breaking nudge.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..geometry import Point
from ..model import Jumper, Strip
from .net_router import Congestion


class NegotiatedCongestion(Congestion):
    def __init__(self, weight: float = 0.5) -> None:
        self.weight = weight
        self.history: dict[Point, float] = {}

    def extra(self, strips: Iterable[Strip], jumpers: Iterable[Jumper]) -> float:
        total = 0.0
        for s in strips:
            for p in s.points():
                total += self.history.get(p, 0.0)
        for j in jumpers:
            for p in (*j.endpoints(), *j.keepout()):
                total += self.history.get(p, 0.0)
        return self.weight * total

    def penalize(self, points: Iterable[Point], amount: float = 1.0) -> None:
        for p in points:
            self.history[p] = self.history.get(p, 0.0) + amount
