"""Result types and options for the top-level :func:`stripboard.router.route`.

Routing infeasibility is *data*, not an exception: each net carries a :class:`NetStatus`
and the whole run an overall :class:`RouteStatus`. Only malformed input (``NetlistError``)
and unrepairable placement (``PlacementError``) raise. If ``RouteOptions.on_infeasible ==
"raise"``, a non-feasible routing raises :class:`RoutingInfeasibleError` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .cost import CostBreakdown
from .geometry import Point
from .model import Routing
from .placement import PlacementOptions
from .routing.ripup import RipupOptions
from .validation import ValidationResult


class RouteStatus(StrEnum):
    FEASIBLE = "feasible"  # every net routed and the layout validates
    PARTIAL = "partial"  # some nets routed, some not
    INFEASIBLE = "infeasible"  # nothing routed


class RoutingInfeasibleError(RuntimeError):
    """Raised by route() when on_infeasible='raise' and the result is not feasible."""


@dataclass(frozen=True)
class NetStatus:
    net_id: str
    routed: bool
    reason: str | None = None


@dataclass(frozen=True)
class Placement:
    instance_id: str
    origin: Point
    flipped: bool


@dataclass(frozen=True)
class RouteOptions:
    on_infeasible: str = "partial"  # "partial" | "raise"
    placement: PlacementOptions = field(default_factory=PlacementOptions)
    ripup: RipupOptions = field(default_factory=RipupOptions)
    # place->route feedback: try this many ranked placements, keep the first feasible one.
    max_placement_attempts: int = 8


@dataclass
class Result:
    status: RouteStatus
    placements: list[Placement]
    routing: Routing
    physical_cuts: set[Point]
    validation: ValidationResult
    cost: CostBreakdown
    net_status: list[NetStatus]
    seed: int

    @property
    def ok(self) -> bool:
        return self.status is RouteStatus.FEASIBLE and self.validation.ok
