"""Seeded randomness and deterministic tie-breaking.

All stochastic search threads a single ``random.Random`` created here -- never the global
``random`` module -- so a given ``seed`` reproduces a run exactly. Ties between equal-cost
candidates are broken by an explicit lexicographic key, also here, so results don't depend
on set/dict iteration order.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable


def make_rng(seed: int) -> random.Random:
    return random.Random(seed)


def argmin_tiebreak[T](
    items: Iterable[T],
    cost: Callable[[T], float],
    key: Callable[[T], object],
) -> T:
    """Return the item minimizing ``cost``, breaking ties by the lexicographic ``key``.

    Deterministic regardless of input iteration order. Raises on an empty input.
    """
    best: T | None = None
    best_cost: float | None = None
    best_key: object = None
    found = False
    for it in items:
        c = cost(it)
        k = key(it)
        if not found or c < best_cost or (c == best_cost and k < best_key):  # type: ignore[operator]
            best, best_cost, best_key, found = it, c, k, True
    if not found:
        raise ValueError("argmin_tiebreak() on an empty iterable")
    return best  # type: ignore[return-value]
