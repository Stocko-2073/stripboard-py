"""The autoroute API: netlist in, jumpers and cuts drawn.

The subtle part is not the solve, it is the *caching* around it. `project()` runs a
board's `draw()` up to five times (three views, plus the label, plus the g-code capture),
and each pass re-declares the same netlist. Without memoization the solver would run five
times and -- worse -- could pick different placements for an unlocked part in different
views, so the FRONT and BACK sheets would disagree about where a component goes.
"""

from __future__ import annotations

import warnings

import pytest

from stripboard import StripBoard, StripboardWarning, UnroutableNetWarning
from tests.helpers import local_pins


def small_board():
    """A board just big enough to route, kept small so the solver stays quick."""
    sb = StripBoard(page_width=24, page_height=28)
    sb.begin_board(12, "M", show_strips=True, at=(0, 0), show_traces=True, title="P")
    return sb


def two_sips_and_a_resistor(sb, *, locked=False):
    a = sb.sip(2, "B", 3, "A", pins=["1", "2", "3"])
    b = sb.sip(10, "B", 3, "B", pins=["1", "2", "3"])
    r = sb.resist(6, "E", l=1, locked=locked)
    sb.net("n1", a.pin("1"), r.pin("1"))
    sb.net("n2", b.pin("1"), r.pin("2"))
    return a, b, r


# ---- solve caching -------------------------------------------------------------------

def test_the_same_problem_solves_once_across_views():
    sb = StripBoard(page_width=24, page_height=28)
    for _ in range(2):
        sb.begin_board(12, "M", show_strips=True, at=(0, 0), title="P")
        two_sips_and_a_resistor(sb, locked=True)
        sb.autoroute(seed=0)
        sb.end_board()
    assert len(sb._route_cache) == 1


def test_a_triptych_solves_once_for_all_three_views():
    """draw() runs per view; the solve must not."""
    def draw(sb):
        two_sips_and_a_resistor(sb, locked=True)
        sb.autoroute(seed=0)

    sb = StripBoard(page_width=48, page_height=28)
    sb.triptych(draw, 12, "M", pitch=15)
    assert len(sb._route_cache) == 1


def test_a_different_seed_is_a_different_solve():
    def draw(sb, seed):
        two_sips_and_a_resistor(sb, locked=True)
        sb.autoroute(seed=seed)

    sb = StripBoard(page_width=24, page_height=28)
    for seed in (0, 1):
        sb.begin_board(12, "M", show_strips=True, at=(0, 0), title="P")
        draw(sb, seed)
        sb.end_board()
    assert len(sb._route_cache) == 2


def test_a_changed_netlist_is_a_different_solve():
    sb = StripBoard(page_width=24, page_height=28)

    sb.begin_board(12, "M", show_strips=True, at=(0, 0), title="P")
    two_sips_and_a_resistor(sb, locked=True)
    sb.autoroute(seed=0)
    sb.end_board()

    sb.begin_board(12, "M", show_strips=True, at=(0, 0), title="P")
    a, b, _ = two_sips_and_a_resistor(sb, locked=True)
    sb.net("n3", a.pin("3"), b.pin("3"))
    sb.autoroute(seed=0)
    sb.end_board()

    assert len(sb._route_cache) == 2


# ---- signature -----------------------------------------------------------------------

def test_signature_ignores_where_the_solver_will_put_unlocked_parts():
    """That exclusion is what lets three views share one solve."""
    sb = small_board()
    two_sips_and_a_resistor(sb, locked=False)
    board, instances, netlist = sb._build_problem()
    first = sb._signature(board, instances, netlist, 0, None)

    moved = [i if i.locked else i.moved((4, 4), False) for i in instances]
    assert sb._signature(board, moved, netlist, 0, None) == first


def test_signature_tracks_where_you_put_locked_parts():
    from dataclasses import replace

    sb = small_board()
    two_sips_and_a_resistor(sb, locked=True)
    board, instances, netlist = sb._build_problem()
    first = sb._signature(board, instances, netlist, 0, None)

    # moved() refuses to relocate a locked instance, which is the point -- build the
    # relocated copy directly to prove the signature notices.
    moved = [replace(instances[0], origin=(5, 5))] + list(instances[1:])
    assert sb._signature(board, moved, netlist, 0, None) != first


# ---- results -------------------------------------------------------------------------

def test_a_routable_board_reports_feasible():
    sb = small_board()
    two_sips_and_a_resistor(sb, locked=True)
    result = sb.autoroute(seed=0)
    assert result.status.value == "feasible"
    assert result.validation.ok
    assert all(ns.routed for ns in result.net_status)
    assert result.cost.total < float("inf")


def test_the_result_is_kept_on_the_board_for_reporting():
    sb = small_board()
    two_sips_and_a_resistor(sb, locked=True)
    result = sb.autoroute(seed=0)
    assert sb.last_result is result


def test_route_report_summarizes_the_solve(capsys):
    sb = small_board()
    two_sips_and_a_resistor(sb, locked=True)
    sb.autoroute(seed=0)
    sb.route_report()
    out = capsys.readouterr().out
    assert "status=feasible" in out
    assert "jumpers=" in out and "cuts=" in out


def test_route_report_is_silent_without_a_solve(capsys):
    small_board().route_report()
    assert capsys.readouterr().out == ""


# ---- auto-placement ------------------------------------------------------------------

def test_an_unlocked_part_is_placed_on_the_board():
    sb = small_board()
    _, _, r = two_sips_and_a_resistor(sb, locked=False)
    result = sb.autoroute(seed=0)
    placed = {p.instance_id: p for p in result.placements}
    assert r.id in placed
    px, py = placed[r.id].origin
    assert 1 <= px <= sb.board_width
    assert 1 <= py <= sb.board_height


def test_redraw_lands_on_the_routers_own_pin_positions():
    """An auto-placed part must be drawn exactly where the solver thinks its pins are.

    The renderer and the solver each compute world positions for a flipped, relocated
    footprint. If they disagree, the PDF shows a component whose legs miss the holes the
    jumpers were routed to.
    """
    sb = small_board()
    d = sb.dip(3, "C", 3, 3, "U", pins=["A", "B", "C", "D", "E", "F"], locked=False)
    R = sb._ensure_router()
    ox, oy = d.origin
    pindefs = tuple(R.PinDef(n, (wx - ox, wy - oy)) for n, (wx, wy) in d.pins.items())
    ctype = R.ComponentType("U", pins=pindefs)

    for flipped in (False, True):
        for origin in ((5, 5), (8, 10)):
            inst = R.ComponentInstance("U", ctype, origin=origin, flipped=flipped)
            drawn = d._redraw(origin[0], origin[1], flipped)
            assert drawn == inst.world_pins(), (flipped, origin)


# ---- the router is reachable directly ------------------------------------------------

def test_the_bundled_router_needs_no_path_setup():
    """It ships inside the package; autoroute() no longer hunts for a sibling checkout."""
    import stripboard.router as router
    assert small_board()._ensure_router() is router
    assert callable(router.route)


# ---- hand-placed links the solver honours ---------------------------------------------

def test_link_pins_sit_at_the_two_soldered_holes():
    sb = small_board()
    ln = sb.link(4, "C", "H")
    assert local_pins(ln) == {"1": (0, 0), "2": (0, 5)}
    assert ln.origin == (4, 3)
    assert ln.locked is True


def test_link_reserves_the_holes_it_arcs_over():
    """A wire's span is a keep-out, so nothing else is routed through it."""
    assert small_board().link(4, "C", "H").keepouts == ((0, 1, 0, 4),)


def test_a_link_between_adjacent_rows_reserves_nothing():
    assert small_board().link(4, "C", "D").keepouts == ()


def test_link_accepts_its_rows_in_either_order():
    sb = small_board()
    down, up = sb.link(4, "C", "H"), sb.link(6, "H", "C")
    assert local_pins(down) == local_pins(up)
    assert down.keepouts == up.keepouts
    assert up.origin == (6, 3)


def test_link_ends_and_span_reach_the_router():
    """The solver must see the wire, or it will route a jumper straight through it."""
    sb = small_board()
    ln = sb.link(4, "C", "H")
    _, instances, _ = sb._build_problem()
    inst = next(i for i in instances if i.id == ln.id)
    assert {p.local_id: p.offset for p in inst.type.pins} == {"1": (0, 0), "2": (0, 5)}
    assert [(r.x0, r.y0, r.x1, r.y1) for r in inst.type.keepouts] == [(0, 1, 0, 4)]


def test_links_are_numbered_like_any_other_part():
    sb = small_board()
    assert [sb.link(4, "C", "H").id, sb.link(6, "C", "H").id] == ["LINK", "LINK2"]


def test_a_link_can_carry_a_net_and_the_board_still_validates():
    """The point of registering a link: hand and auto routing on one board."""
    sb = small_board()
    a = sb.sip(2, "B", 3, "A", pins=["1", "2", "3"])
    b = sb.sip(10, "B", 3, "B", pins=["1", "2", "3"])
    ln = sb.link(6, "F", "J")
    sb.net("n1", a.pin("1"), ln.pin("1"))
    sb.net("n2", b.pin("1"), ln.pin("2"))
    result = sb.autoroute(seed=0)
    assert result.status.value == "feasible"
    assert result.validation.ok, result.validation.summary()


def test_autorouted_jumpers_avoid_a_links_span():
    sb = small_board()
    a = sb.sip(2, "B", 3, "A", pins=["1", "2", "3"])
    b = sb.sip(10, "B", 3, "B", pins=["1", "2", "3"])
    sb.link(6, "C", "K")
    sb.net("n1", a.pin("1"), b.pin("1"))
    result = sb.autoroute(seed=0)
    assert result.validation.ok, result.validation.summary()
    reserved = {(6, y) for y in range(4, 11)} | {(6, 3), (6, 11)}
    assert all((j.x, j.ya) not in reserved and (j.x, j.yb) not in reserved
               for j in result.routing.all_jumpers())


# ---- a net the geometry cannot route --------------------------------------------------

def trapped_net_board():
    """A net whose two pins straddle a foreign pin on one row.

    Row C's strip has to reach both of the net's pins, so it would have to cover the
    pin between them. No ordering, jumper column or detour row can avoid that.
    """
    sb = small_board()
    a = sb.sip(2, "C", 1, "A", pins=["1"])
    b = sb.sip(10, "C", 1, "B", pins=["1"])
    sb.sip(6, "C", 1, "X", pins=["1"])
    sb.net("n1", a.pin("1"), b.pin("1"))
    return sb


def test_an_unroutable_net_warns_and_says_what_is_in_the_way():
    with pytest.warns(UnroutableNetWarning) as caught:
        result = trapped_net_board().autoroute(seed=0)
    assert result.status.value == "partial"
    message = str(caught[0].message)
    assert "'n1'" in message
    assert "X.1 at (6,3)" in message


def test_an_unroutable_net_can_be_made_a_build_failure():
    """Escalating the warning is how a board file refuses to ship a half-wired board."""
    sb = trapped_net_board()
    with warnings.catch_warnings():
        warnings.simplefilter("error", StripboardWarning)
        with pytest.raises(UnroutableNetWarning):
            sb.autoroute(seed=0)


def test_a_fully_routed_board_stays_quiet():
    sb = small_board()
    two_sips_and_a_resistor(sb, locked=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error", StripboardWarning)
        assert sb.autoroute(seed=0).status.value == "feasible"


def test_the_warning_is_attributed_to_the_calling_board_file():
    with pytest.warns(UnroutableNetWarning) as caught:
        trapped_net_board().autoroute(seed=0)
    assert caught[0].filename == __file__


# ---- the build-sheet report -----------------------------------------------------------

def solved_board():
    sb = small_board()
    two_sips_and_a_resistor(sb, locked=True)
    sb.autoroute(seed=0)
    return sb


def test_the_default_report_stays_a_summary(capsys):
    solved_board().route_report()
    out = capsys.readouterr().out
    assert "status=feasible" in out
    assert "wire:" not in out
    assert "cuts under a part body" not in out


def test_verbose_lists_every_jumper_with_its_length(capsys):
    sb = solved_board()
    sb.route_report(verbose=True)
    out = capsys.readouterr().out
    wire = sum(j.vlength() for j in sb.last_result.routing.all_jumpers())
    assert f"{wire} holes end to end" in out
    for net_id, jumpers in sb.last_result.routing.jumpers.items():
        assert net_id in out
        for j in jumpers:
            assert f"{j.x} {sb.row_name(j.ya)}-{sb.row_name(j.yb)} ({j.vlength()})" in out


def test_verbose_counts_the_cuts_buried_under_a_part(capsys):
    sb = solved_board()
    sb.route_report(verbose=True)
    out = capsys.readouterr().out
    buried = sb.cuts_under_bodies()
    assert f"cuts under a part body: {len(buried)} of {sb.last_result.cost.num_cuts}" in out


def test_buried_cuts_are_the_ones_that_land_on_a_part_body():
    """They have to be made before the part goes on, so they drive build order."""
    sb = StripBoard(page_width=40, page_height=40)
    sb.begin_board(20, "P", show_strips=True, at=(0, 0), show_traces=True, title="P")
    d = sb.stepstick(3, "C", "DRV")
    h = sb.sip(16, "C", 1, "H", pins=["a"])
    sb.net("VM", d.pin("VM"), h.pin("a"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", StripboardWarning)
        sb.autoroute(seed=0)
    buried = sb.cuts_under_bodies()
    body = {p for r in sb._placed_instances(sb.last_result)
            for rect in r.world_keepouts() for p in rect.points()}
    assert set(buried) <= body
    assert set(buried) == sb.last_result.physical_cuts & body


def test_the_report_is_silent_without_a_solve_however_verbose(capsys):
    sb = small_board()
    sb.route_report(verbose=True)
    assert capsys.readouterr().out == ""
    assert sb.cuts_under_bodies() == []
