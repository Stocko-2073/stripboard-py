"""The handle a part builder hands back."""

from __future__ import annotations

__all__ = ["Component"]


class Component:
    """Handle returned by a StripBoard part builder (``xiao``/``dip``/``sip``/...).

    Carries the part's pin holes in *world* coordinates so the autorouter can build a
    footprint from the exact geometry the renderer drew (one source of truth), plus a
    redraw closure so an unlocked (auto-placed) part can be rendered where the solver
    placed it. Existing callers that ignore the return value are unaffected.

    Pins are addressed by name via :meth:`pin`, which returns the ``(instance_id,
    local_id)`` reference the netlist uses -- e.g. ``sb.net('WS', mic.pin('WS'), ...)``.
    """

    def __init__(self, id, pins, origin, locked=True, keepouts=(), internal=(), redraw=None):
        self.id = id
        self.pins = dict(pins)              # name -> world (x, y) hole
        self.origin = origin                # (x, y) world of the draw call
        self.locked = locked
        self.keepouts = tuple(keepouts)     # local rects as (x0, y0, x1, y1) tuples
        self.internal = tuple(internal)     # tuple[frozenset[str]] of internally-tied pins
        self._redraw = redraw               # callable(origin, flipped) -> None (deferred draw)

    def pin(self, name):
        """Return the ``(instance_id, name)`` netlist reference for pin ``name``.

        Numeric pins may be given as an ``int`` for convenience -- e.g.
        ``c1.pin(2)`` is equivalent to ``c1.pin('2')``.
        """
        if isinstance(name, int):
            name = str(name)
        if name not in self.pins:
            raise KeyError(
                f"Component {self.id!r} has no pin {name!r}; available: {sorted(self.pins)}"
            )
        return (self.id, name)

    def __repr__(self):
        return f"Component({self.id!r}, pins={sorted(self.pins)}, locked={self.locked})"
