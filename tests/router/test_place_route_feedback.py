"""Place->route feedback loop + congestion scoring (regression for the pengui-phone bug).

Unlocking a tall resistor in the pengui-phone design made routing fail: Phase-1 placement
minimizes HPWL only and parked the resistor's 8-cell body keep-out in the congested middle
of the board (wirelength-optimal, but Phase 2 could not route around it). Two fixes work
together here:

* the pipeline now tries several ranked placements and keeps the first routable one
  (``max_placement_attempts``), and
* placement scoring adds a congestion penalty (``PlacementOptions.w_cong``) so the routable
  placement tends to rank first in the first place.

The fixture below is the exact stripboard.router problem produced by ``pengui_phone_auto.py``
(captured as primitives so this test does not depend on ``stripboard.py``).
"""

from __future__ import annotations

import pytest

import stripboard.router as R
from stripboard.router.geometry import Rect
from stripboard.router.model import Board, ComponentInstance, ComponentType, Net, PinDef
from stripboard.router.placement import PlacementOptions
from stripboard.router.result import RouteOptions, RouteStatus

# Every test here drives the full place->route pipeline with retries, which is by far the
# slowest thing in the suite (~3 minutes for the four of them). Deselected by default;
# run them with `pytest -m ''` or `pytest -m slow`.
pytestmark = pytest.mark.slow


def _type(name, pins, keepouts=()):
    return ComponentType(
        name,
        pins=tuple(PinDef(lid, off) for lid, off in pins),
        keepouts=tuple(Rect.of(*k) for k in keepouts),
    )


def pengui_problem():
    """The pengui-phone board with the resistor ``R`` unlocked (origin is its hand column)."""
    xiao = ComponentInstance("XIAO", _type("XIAO", [
        ("D0", (6, 6)), ("D1", (6, 5)), ("D2", (6, 4)), ("D3", (6, 3)), ("D4", (6, 2)),
        ("D5", (6, 1)), ("TX", (6, 0)), ("RX", (0, 0)), ("D8", (0, 1)), ("D9", (0, 2)),
        ("D10", (0, 3)), ("3V3", (0, 4)), ("GND", (0, 5)), ("5V", (0, 6)),
    ]), origin=(5, 20), locked=True)
    mic = ComponentInstance("MIC", _type("MIC", [
        ("LR", (3, 2)), ("WS", (3, 1)), ("SCK", (3, 0)), ("SD", (0, 0)), ("3V", (0, 1)),
        ("GND", (0, 2)),
    ]), origin=(8, 16), locked=True)
    amp = ComponentInstance("AMP", _type("AMP", [
        ("LRC", (0, 6)), ("BCLK", (0, 5)), ("DIN", (0, 4)), ("GAIN", (0, 3)), ("SD", (0, 2)),
        ("GND", (0, 1)), ("VIN", (0, 0)),
    ]), origin=(13, 4), locked=True)
    btn = ComponentInstance("BTN", _type("BTN", [
        ("AL", (0, 0)), ("BL", (0, 2)), ("AR", (5, 0)), ("BR", (5, 2)),
    ], keepouts=[(1, -1, 4, 3)]), origin=(13, 12), locked=True)
    led = ComponentInstance("LED", _type("LED", [("A", (0, 0)), ("K", (0, 1))]),
                            origin=(17, 18), locked=True)
    res = ComponentInstance("R", _type("R", [("1", (0, 0)), ("2", (0, 8))],
                                       keepouts=[(0, 1, 0, 7)]), origin=(18, 18), locked=False)
    cap = ComponentInstance("C", _type("C", [("1", (0, 0)), ("2", (0, 1))]),
                            origin=(17, 4), locked=True)
    instances = [xiao, mic, amp, btn, led, res, cap]

    def net(nid, *pins):
        return Net(nid, frozenset(pins))

    netlist = [
        net("GND", ("AMP", "GAIN"), ("AMP", "GND"), ("BTN", "AL"), ("BTN", "AR"),
            ("C", "2"), ("LED", "K"), ("MIC", "GND"), ("XIAO", "GND")),
        net("WS", ("AMP", "LRC"), ("MIC", "WS"), ("XIAO", "D8")),
        net("5V", ("AMP", "VIN"), ("C", "1"), ("XIAO", "5V")),
        net("SCK", ("AMP", "BCLK"), ("MIC", "SCK"), ("XIAO", "D5")),
        net("BTN", ("BTN", "BL"), ("BTN", "BR"), ("XIAO", "D1")),
        net("DIN", ("AMP", "DIN"), ("XIAO", "D9")),
        net("3V3", ("MIC", "3V"), ("XIAO", "3V3")),
        net("SD", ("MIC", "SD"), ("XIAO", "D4")),
        net("R_D0", ("R", "2"), ("XIAO", "D0")),
        net("LED", ("LED", "A"), ("R", "1")),
    ]
    return Board(18, 26), instances, netlist


def _run(*, attempts, w_cong):
    board, instances, netlist = pengui_problem()
    opts = RouteOptions(
        max_placement_attempts=attempts,
        placement=PlacementOptions(w_cong=w_cong),
    )
    return R.route(board, instances, netlist, seed=0, options=opts)


def test_bug_repro_single_attempt_no_congestion():
    """The original failure: one HPWL-only placement is unroutable (documents the gap)."""
    res = _run(attempts=1, w_cong=0.0)
    assert res.status is not RouteStatus.FEASIBLE
    assert not res.validation.ok
    r_origin = next(p.origin for p in res.placements if p.instance_id == "R")
    assert r_origin != (18, 18)  # HPWL pulled the resistor off its routable hand column


def test_retry_loop_recovers_without_congestion():
    """Option 2 alone: the feedback loop finds a routable placement after the first fails."""
    res = _run(attempts=8, w_cong=0.0)
    assert res.status is RouteStatus.FEASIBLE
    assert res.validation.ok
    assert all(ns.routed for ns in res.net_status)


def test_congestion_makes_first_placement_routable():
    """Option 3 alone: congestion scoring ranks a routable placement first (attempts=1)."""
    res = _run(attempts=1, w_cong=0.5)
    assert res.status is RouteStatus.FEASIBLE
    assert res.validation.ok
    assert all(ns.routed for ns in res.net_status)


def test_default_options_route_feasible():
    """Both together (defaults): fully routed and valid."""
    board, instances, netlist = pengui_problem()
    res = R.route(board, instances, netlist, seed=0)
    assert res.status is RouteStatus.FEASIBLE
    assert res.validation.ok
    assert all(ns.routed for ns in res.net_status)
