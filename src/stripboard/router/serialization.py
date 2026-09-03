"""JSON serialization for :class:`Result` (stdlib ``json`` only).

Points serialize as ``[x, y]`` pairs and sets as sorted lists, so the output is stable and
diff-friendly. ``to_dict``/``from_dict`` round-trip a Result; ``dump``/``load`` wrap the
same over file objects.
"""

from __future__ import annotations

import json
from typing import IO, Any

from .cost import CostBreakdown
from .model import Jumper, Routing, Strip, Weights
from .result import NetStatus, Placement, Result, RouteStatus
from .validation import ValidationResult, Violation


def _pt(p: tuple[int, int]) -> list[int]:
    return [p[0], p[1]]


def to_dict(result: Result) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "seed": result.seed,
        "placements": [
            {"instance_id": pl.instance_id, "origin": _pt(pl.origin), "flipped": pl.flipped}
            for pl in result.placements
        ],
        "routing": {
            "strips": {
                nid: [[s.y, s.xa, s.xb] for s in ss]
                for nid, ss in sorted(result.routing.strips.items())
            },
            "jumpers": {
                nid: [[j.x, j.ya, j.yb] for j in js]
                for nid, js in sorted(result.routing.jumpers.items())
            },
        },
        "physical_cuts": [_pt(p) for p in sorted(result.physical_cuts)],
        "validation": {
            "ok": result.validation.ok,
            "violations": [
                {"code": v.code, "message": v.message, "points": [_pt(p) for p in v.points]}
                for v in result.validation.violations
            ],
        },
        "cost": {
            "weighted_net_length": result.cost.weighted_net_length,
            "num_jumpers": result.cost.num_jumpers,
            "num_cuts": result.cost.num_cuts,
            "total": result.cost.total,
            "weights": vars(result.cost.weights),
        },
        "net_status": [
            {"net_id": ns.net_id, "routed": ns.routed, "reason": ns.reason}
            for ns in result.net_status
        ],
    }


def from_dict(data: dict[str, Any]) -> Result:
    routing = Routing()
    for nid, ss in data["routing"]["strips"].items():
        for y, xa, xb in ss:
            routing.add_strip(Strip(y, xa, xb, nid))
    for nid, js in data["routing"]["jumpers"].items():
        for x, ya, yb in js:
            routing.add_jumper(Jumper(x, ya, yb, nid))

    validation = ValidationResult(
        [
            Violation(v["code"], v["message"], tuple((p[0], p[1]) for p in v["points"]))
            for v in data["validation"]["violations"]
        ]
    )
    c = data["cost"]
    cost = CostBreakdown(
        c["weighted_net_length"], c["num_jumpers"], c["num_cuts"], Weights(**c["weights"])
    )
    return Result(
        status=RouteStatus(data["status"]),
        placements=[
            Placement(pl["instance_id"], (pl["origin"][0], pl["origin"][1]), pl["flipped"])
            for pl in data["placements"]
        ],
        routing=routing,
        physical_cuts={(p[0], p[1]) for p in data["physical_cuts"]},
        validation=validation,
        cost=cost,
        net_status=[
            NetStatus(ns["net_id"], ns["routed"], ns["reason"]) for ns in data["net_status"]
        ],
        seed=data["seed"],
    )


def dumps(result: Result, *, indent: int | None = 2) -> str:
    return json.dumps(to_dict(result), indent=indent, sort_keys=False)


def loads(s: str) -> Result:
    return from_dict(json.loads(s))


def dump(result: Result, fp: IO[str], *, indent: int | None = 2) -> None:
    json.dump(to_dict(result), fp, indent=indent, sort_keys=False)


def load(fp: IO[str]) -> Result:
    return from_dict(json.load(fp))
