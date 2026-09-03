"""The autoroute API: netlist in, jumpers and cuts drawn.

The subtle part is not the solve, it is the *caching* around it. `project()` runs a
board's `draw()` up to five times (three views, plus the label, plus the g-code capture),
and each pass re-declares the same netlist. Without memoization the solver would run five
times and -- worse -- could pick different placements for an unlocked part in different
views, so the FRONT and BACK sheets would disagree about where a component goes.
"""

from __future__ import annotations

from stripboard import StripBoard


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
