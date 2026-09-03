"""Driving the bundled autorouter and drawing what it returns.

The translation layer between a drawn board and :mod:`stripboard.router`: it turns
registered components and declared nets into a solver problem, caches the solve by
signature, and renders the resulting jumpers and cuts back onto the board.

The cache matters more than it looks. `project()` runs a board's `draw()` up to five
times, and each pass re-declares the same netlist; the signature deliberately excludes
solver-chosen positions so all those passes hit one solve and therefore agree about where
an auto-placed part went.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Resolves the state and sibling methods every mixin shares; see _state.py. At
    # runtime the base is `object`, so the MRO is unchanged.
    from ._state import BoardState as _Base
else:
    _Base = object

__all__ = ["AutorouteMixin"]


class AutorouteMixin(_Base):
    def _ensure_router(self):
        """Return the autorouter module (:mod:`stripboard.router`).

        The router ships inside this package, so this is just an accessor now -- it
        survives as a method because the netlist/autoroute code and the tests reach for
        the router through it.
        """
        if self._router is None:
            from . import router
            self._router = router
        return self._router

    def _build_problem(self):
        """Translate registered components + declared nets into router inputs."""
        R = self._ensure_router()
        instances = []
        for c in self._route_components:
            ox, oy = c.origin
            pindefs = tuple(R.PinDef(name, (wx - ox, wy - oy))
                            for name, (wx, wy) in c.pins.items())
            keepouts = tuple(R.Rect.of(*ko) for ko in c.keepouts)
            ctype = R.ComponentType(c.id, pins=pindefs, keepouts=keepouts,
                                    internal=tuple(c.internal))
            instances.append(R.ComponentInstance(c.id, ctype, origin=c.origin, locked=c.locked))
        netlist = [R.Net(nid, refs, weight=w) for (nid, refs, w) in self._resolve_nets()]
        board = R.Board(w=self.board_width, h=self.board_height)
        return board, instances, netlist

    def _signature(self, board, instances, netlist, seed, weights):
        """Hashable key identifying the solve. Excludes unlocked origins (solver-chosen),
        so the same board rendered in three views hits the cache after the first solve."""
        comp_sig = tuple(sorted(
            (i.id, i.locked, i.origin if i.locked else None, i.flipped,
             tuple(sorted((p.local_id, p.offset) for p in i.type.pins)),
             tuple(sorted((r.x0, r.y0, r.x1, r.y1) for r in i.type.keepouts)),
             tuple(sorted(tuple(sorted(g)) for g in i.type.internal)))
            for i in instances))
        net_sig = tuple(sorted((n.id, tuple(sorted(n.pins)), n.weight) for n in netlist))
        w = None if weights is None else (
            weights.w_len, weights.w_jmp, weights.w_cut, weights.w_x, weights.w_y)
        return (board.w, board.h, comp_sig, net_sig, seed, w)

    def autoroute(self, *, seed=0, weights=None, options=None, net_colors=None,
                  show_cuts=True, show_keepouts=False, on_infeasible="partial"):
        """Solve the declared netlist and draw jumpers/cuts (and auto-placed parts).

        Idempotent across views: the solve is cached by signature, so calling this inside a
        draw lambda that runs once per view solves only the first time. Returns the
        router ``Result`` (status, cost, validation, per-net status)."""
        R = self._ensure_router()
        board, instances, netlist = self._build_problem()
        wobj = R.Weights(**weights) if isinstance(weights, dict) else weights
        sig = self._signature(board, instances, netlist, seed, wobj)
        result = self._route_cache.get(sig)
        if result is None:
            opts = options or R.RouteOptions(on_infeasible=on_infeasible)
            result = R.route(board, instances, netlist, weights=wobj, seed=seed, options=opts)
            self._route_cache[sig] = result
        placements = {p.instance_id: p for p in result.placements}
        for c in self._route_components:
            if not c.locked and c._redraw is not None:
                p = placements.get(c.id)
                if p is not None:
                    c._redraw(p.origin[0], p.origin[1], p.flipped)
        self._render_routing(result, net_colors=net_colors, show_cuts=show_cuts)
        if show_keepouts:
            # Shade keep-outs where the solver *placed* each part, not where it was drawn --
            # an unlocked part and its body keep-out move together (locked parts are unchanged).
            placed = [
                inst.moved(p.origin, p.flipped)
                if not inst.locked and (p := placements.get(inst.id)) is not None
                else inst
                for inst in instances
            ]
            self._render_keepouts(placed)
        self.last_result = result
        return result

    def _render_routing(self, result, net_colors=None, show_cuts=True):
        """Draw a router Result's jumpers + cuts onto this board (current view)."""
        colors = dict(self._net_colors)
        if net_colors:
            colors.update(net_colors)
        for net_id in sorted(result.routing.jumpers):
            color = colors.get(net_id)
            for j in result.routing.jumpers[net_id]:
                if color is None:
                    self.jumper(j.x, j.ya, j.x, j.yb)
                else:
                    self.jumper(j.x, j.ya, j.x, j.yb, color=color)
        if show_cuts:
            for x, y in sorted(result.physical_cuts):
                self.cut(x, y)

    def _shade_rect(self, x, y, w, h, color=(255, 140, 0)):
        """Draw a translucent, outlined rectangle (the keep-out region style)."""
        self.color(*color)
        self.pdf.set_alpha(0.22)
        self._rect(x, y, w, h, "F")
        self.pdf.set_alpha(1.0)
        self._rect(x, y, w, h, "S")
        self.black()

    def _render_keepouts(self, instances, color=(255, 140, 0)):
        """Shade each instance's keep-out rectangles (e.g. a button body)."""
        for inst in instances:
            for r in inst.world_keepouts():
                self._shade_rect(r.x0 - 0.5, r.y0 - 0.5,
                                 r.x1 - r.x0 + 1, r.y1 - r.y0 + 1, color)

    def route_report(self, result=None, *, file=None):
        """Print the standard autoroute summary (status/routed/jumpers/cuts + unrouted nets).

        Uses ``self.last_result`` (set by :meth:`autoroute`) when no result is passed; a
        no-op for hand-routed boards that never called autoroute()."""
        r = result if result is not None else self.last_result
        if r is None:
            return
        routed = sum(1 for ns in r.net_status if ns.routed)
        print(f"status={r.status.value} valid={r.validation.ok} "
              f"routed={routed}/{len(r.net_status)} "
              f"jumpers={r.cost.num_jumpers} cuts={r.cost.num_cuts} cost={r.cost.total}",
              file=file)
        print(f"solves cached: {len(self._route_cache)}", file=file)
        for ns in r.net_status:
            if not ns.routed:
                print(f"  UNROUTED {ns.net_id}: {ns.reason}", file=file)
