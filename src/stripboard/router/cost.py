"""Routing objective (spec section 7).

    cost = w_len * Sum_nets w_net * netLength      (electrical diameter, section 4.3)
         + w_jmp * (number of jumpers)
         + w_cut * (number of distinct physical cuts)

Everything is a pure recomputation from ``(board, instances, netlist, routing)``; nothing
is cached. The cut count is the number of *distinct physical cut positions* (a cut shared
by two same-row strips counts once).
"""

from __future__ import annotations

from dataclasses import dataclass

from .cuts import physical_cuts
from .model import Board, ComponentInstance, Net, Weights
from .netgraph import net_length
from .netlist import (
    ResolvedNetlist,
    internal_tie_pairs,
    pin_world_positions,
    resolve,
)


@dataclass(frozen=True)
class CostBreakdown:
    weighted_net_length: float  # Sum_nets w_net * netLength
    num_jumpers: int
    num_cuts: int
    weights: Weights

    @property
    def total(self) -> float:
        w = self.weights
        return (
            w.w_len * self.weighted_net_length
            + w.w_jmp * self.num_jumpers
            + w.w_cut * self.num_cuts
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "weighted_net_length": self.weighted_net_length,
            "num_jumpers": self.num_jumpers,
            "num_cuts": self.num_cuts,
            "total": self.total,
        }


def compute_cost(
    board: Board,
    instances: list[ComponentInstance],
    netlist: list[Net],
    routing,
    *,
    weights: Weights | None = None,
) -> CostBreakdown:
    """Public cost: resolves the netlist, then evaluates spec section 7."""
    resolved = resolve(instances, netlist)
    return cost_resolved(board, instances, resolved, routing, weights=weights)


def cost_resolved(
    board: Board,
    instances: list[ComponentInstance],
    resolved: ResolvedNetlist,
    routing,
    *,
    weights: Weights | None = None,
) -> CostBreakdown:
    """Cost from an already-resolved netlist (fast path for the router)."""
    w = weights if weights is not None else board.weights
    pin_pos = pin_world_positions(instances)
    internal_pairs = internal_tie_pairs(instances)

    weighted_len = 0.0
    for net in resolved.nets:
        pins = sorted(net.pins)
        pairs = [(a, b) for (a, b) in internal_pairs if a in net.pins and b in net.pins]
        nl = net_length(
            pins, pin_pos, routing.strips_of(net.id), routing.jumpers_of(net.id), pairs
        )
        weighted_len += net.weight * nl

    num_jumpers = len(routing.all_jumpers())
    num_cuts = len(physical_cuts(routing.all_strips(), board.w, board.h))
    return CostBreakdown(weighted_len, num_jumpers, num_cuts, w)
