"""Declaring electrical intent: `net()` groups and `connect()` edges.

This is the input side of autorouting. `net()` names a group of pins outright; `connect()`
states one edge at a time and the edges are closed into nets with union-find, so chained
calls that share a pin become a single net rather than several overlapping ones.
"""

from __future__ import annotations

from .component import Component

__all__ = ["NetlistMixin"]


class NetlistMixin:
    def _register(self, base, pinmap, origin, locked, keepouts=(), internal=(), redraw=None):
        """Record a built Component (auto-numbering its id) and return the handle."""
        n = self._ref_counters.get(base, 0) + 1
        self._ref_counters[base] = n
        cid = base if n == 1 else f"{base}{n}"
        comp = Component(cid, pinmap, origin, locked, keepouts, internal, redraw)
        self._route_components.append(comp)
        return comp

    def _as_ref(self, p):
        """Coerce a pin argument to a (instance_id, local_id) reference."""
        if (isinstance(p, tuple) and len(p) == 2
                and isinstance(p[0], str) and isinstance(p[1], str)):
            return p
        raise TypeError(
            f"net()/connect() expect pin references from handle.pin('name'); got {p!r}")

    def net(self, net_id, *pins, weight=1.0, color=None):
        """Declare an electrical net joining the given pins (``handle.pin('name')``)."""
        refs = frozenset(self._as_ref(p) for p in pins)
        self._route_nets.append((net_id, refs, weight))
        if color is not None:
            self._net_colors[net_id] = color
        return self

    def connect(self, a, b, *, weight=1.0, color=None):
        """Two-pin sugar: connect ``a`` to ``b``. Chained connects sharing a pin merge
        into one net (union-find in :meth:`_build_problem`)."""
        self._route_edges.append((self._as_ref(a), self._as_ref(b), weight, color))
        return self

    def _resolve_nets(self):
        """Explicit net() groups, plus connect() edges closed into nets via union-find."""
        nets = [(nid, set(refs), w) for (nid, refs, w) in self._route_nets]
        if self._route_edges:
            parent = {}

            def find(p):
                parent.setdefault(p, p)
                while parent[p] != p:
                    parent[p] = parent[parent[p]]
                    p = parent[p]
                return p

            groups, colors = {}, {}
            for a, b, _w, _color in self._route_edges:
                parent[find(a)] = find(b)
            for a, b, _w, color in self._route_edges:
                groups.setdefault(find(a), set()).update((a, b))
                if color is not None:
                    colors[find(a)] = color
            for i, (root, refs) in enumerate(sorted(groups.items()), 1):
                nid = f"net{i}"
                nets.append((nid, refs, 1.0))
                if root in colors:
                    self._net_colors[nid] = colors[root]
        return [(nid, frozenset(refs), w) for (nid, refs, w) in nets]
