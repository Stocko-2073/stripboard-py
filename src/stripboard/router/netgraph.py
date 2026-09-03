"""Electrical graph and net length (spec section 4.3).

A net is modelled as a weighted graph whose nodes are **conductive sites** -- the net's
pins and jumper endpoints, each at a definite ``(x, y)``. A strip is *not* collapsed to a
single node (that would erase horizontal distance). Edges:

* **same-strip travel** -- two sites on the same strip: weight ``|dx|``;
* **jumper** -- its two endpoints: weight ``vlength``;
* **internal connection** -- two internally-tied pins: weight 0.

Net length is the electrical **diameter**: the max over all pin pairs of the
shortest-path distance. It is *not* total routed copper.
"""

from __future__ import annotations

import math

from .geometry import Point
from .model import Jumper, PinRef, Strip

Site = tuple  # ("pin", ref) | ("end", jumper_index, endpoint_index)


def _sites(
    pins: list[PinRef],
    pin_pos: dict[PinRef, Point],
    jumpers: list[Jumper],
) -> dict[Site, Point]:
    sites: dict[Site, Point] = {}
    for ref in pins:
        sites[("pin", ref)] = pin_pos[ref]
    for ji, j in enumerate(jumpers):
        e0, e1 = j.endpoints()
        sites[("end", ji, 0)] = e0
        sites[("end", ji, 1)] = e1
    return sites


def _all_pairs(
    pins: list[PinRef],
    pin_pos: dict[PinRef, Point],
    strips: list[Strip],
    jumpers: list[Jumper],
    internal_pairs: list[tuple[PinRef, PinRef]],
) -> tuple[dict[Site, Point], list[Site], list[list[float]]]:
    """Floyd-Warshall all-pairs shortest paths over the net's conductive sites."""
    sites = _sites(pins, pin_pos, jumpers)
    keys = list(sites)
    n = len(keys)
    index = {k: i for i, k in enumerate(keys)}
    INF = math.inf
    d = [[INF] * n for _ in range(n)]
    for i in range(n):
        d[i][i] = 0.0

    def relax(a: Site, b: Site, w: float) -> None:
        i, j = index[a], index[b]
        if w < d[i][j]:
            d[i][j] = d[j][i] = w

    # same-strip travel
    for s in strips:
        on = [k for k, p in sites.items() if s.contains(p)]
        for ia in range(len(on)):
            for ib in range(ia + 1, len(on)):
                ka, kb = on[ia], on[ib]
                relax(ka, kb, abs(sites[ka][0] - sites[kb][0]))
    # jumpers
    for ji, j in enumerate(jumpers):
        relax(("end", ji, 0), ("end", ji, 1), float(j.vlength()))
    # internal connections (length 0)
    for a, b in internal_pairs:
        if ("pin", a) in index and ("pin", b) in index:
            relax(("pin", a), ("pin", b), 0.0)

    for k in range(n):
        dk = d[k]
        for i in range(n):
            dik = d[i][k]
            if dik == INF:
                continue
            di = d[i]
            for jx in range(n):
                nd = dik + dk[jx]
                if nd < di[jx]:
                    di[jx] = nd
    return sites, keys, d


def net_length(
    pins: list[PinRef],
    pin_pos: dict[PinRef, Point],
    strips: list[Strip],
    jumpers: list[Jumper],
    internal_pairs: list[tuple[PinRef, PinRef]],
) -> float:
    """Electrical diameter: max shortest-path over all pin pairs (spec section 4.3).

    Returns ``math.inf`` if any pin pair is unreachable (net not fully connected).
    Single-pin (or empty) nets have length 0.
    """
    if len(pins) <= 1:
        return 0.0
    sites, keys, d = _all_pairs(pins, pin_pos, strips, jumpers, internal_pairs)
    index = {k: i for i, k in enumerate(keys)}
    pin_keys = [("pin", ref) for ref in pins]
    diameter = 0.0
    for a in range(len(pin_keys)):
        for b in range(a + 1, len(pin_keys)):
            dist = d[index[pin_keys[a]]][index[pin_keys[b]]]
            if dist > diameter:
                diameter = dist
    return diameter


def is_connected(
    pins: list[PinRef],
    pin_pos: dict[PinRef, Point],
    strips: list[Strip],
    jumpers: list[Jumper],
    internal_pairs: list[tuple[PinRef, PinRef]],
) -> bool:
    """True iff all the net's pins lie in one connected component (spec section 4.2)."""
    if len(pins) <= 1:
        return True
    return not math.isinf(
        net_length(pins, pin_pos, strips, jumpers, internal_pairs)
    )
