"""The stripboard autorouter: compute valid stripboard layouts from a netlist.

Given a board, placed component instances and a netlist, :func:`route` computes
component placements, horizontal copper strips, vertical jumper wires and the derived
track cuts, minimizing a weighted cost of net length, jumpers and cuts. It is stdlib-only
and emits plain data -- rendering is the caller's job.

Most users never import this directly: :class:`stripboard.StripBoard` drives it through
``sb.net()`` / ``sb.connect()`` / ``sb.autoroute()``, which also draws the result. Import
it when you want the solver on its own.

Public API. Input types, routed/output types, and the top-level functions a consumer
needs. See ``docs/router-spec.md`` for the normative specification and
``docs/router-notes.md`` for design rationale.
"""

from __future__ import annotations

from .cost import CostBreakdown, compute_cost
from .cuts import physical_cuts
from .diagnose import (
    Blocker,
    NetExplanation,
    RowConflict,
    RowPair,
    RowPins,
    explain_net,
    row_conflicts,
)
from .geometry import Point, Rect, manhattan, parse_row
from .model import (
    Board,
    ComponentInstance,
    ComponentType,
    Jumper,
    Net,
    PinDef,
    PinRef,
    Routing,
    Strip,
    Weights,
)
from .netgraph import is_connected, net_length
from .netlist import NetlistError, ResolvedNet, ResolvedNetlist, resolve
from .pipeline import route
from .placement import (
    PlacementError,
    PlacementOptions,
    congestion_field,
    congestion_penalty,
    hpwl,
    is_legal,
    place,
    place_candidates,
)
from .result import (
    NetStatus,
    Placement,
    Result,
    RouteOptions,
    RouteStatus,
    RoutingInfeasibleError,
)
from .routing.ripup import RipupOptions
from .serialization import dump, dumps, from_dict, load, loads, to_dict
from .validation import ValidationResult, Violation, validate

__all__ = [
    # geometry
    "Point",
    "Rect",
    "manhattan",
    "parse_row",
    # model / input
    "Board",
    "Weights",
    "PinDef",
    "PinRef",
    "ComponentType",
    "ComponentInstance",
    "Net",
    # model / routed
    "Strip",
    "Jumper",
    "Routing",
    # netlist resolution
    "resolve",
    "ResolvedNet",
    "ResolvedNetlist",
    "NetlistError",
    # functions
    "physical_cuts",
    "validate",
    "ValidationResult",
    "Violation",
    "net_length",
    "is_connected",
    "compute_cost",
    "CostBreakdown",
    # diagnostics
    "explain_net",
    "NetExplanation",
    "RowPins",
    "RowPair",
    "Blocker",
    "row_conflicts",
    "RowConflict",
    # placement
    "place",
    "place_candidates",
    "congestion_field",
    "congestion_penalty",
    "hpwl",
    "is_legal",
    "PlacementError",
    "PlacementOptions",
    # pipeline / result
    "route",
    "Result",
    "RouteStatus",
    "RouteOptions",
    "RipupOptions",
    "NetStatus",
    "Placement",
    "RoutingInfeasibleError",
    # serialization
    "to_dict",
    "from_dict",
    "dump",
    "load",
    "dumps",
    "loads",
]
