"""Property-based tests (Hypothesis) for structural invariants."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from stripboard.router.cuts import physical_cuts
from stripboard.router.geometry import Rect, flip_point
from stripboard.router.model import Strip
from stripboard.router.netgraph import net_length

W, H = 34, 26


@st.composite
def same_row_strips(draw):
    """A list of non-overlapping strips on one row, with >= 1 empty column between them."""
    y = draw(st.integers(1, H))
    strips = []
    x = draw(st.integers(1, 3))
    for i in range(draw(st.integers(1, 6))):
        length = draw(st.integers(0, 4))
        xa = x
        xb = min(W, x + length)
        if xa > W:
            break
        strips.append(Strip(y, xa, xb, f"n{i}"))
        x = xb + 2 + draw(st.integers(0, 3))  # enforce a gap of at least one column
    return strips


@given(same_row_strips())
def test_physical_cuts_invariant_under_ordering(strips):
    assert physical_cuts(strips, W, H) == physical_cuts(list(reversed(strips)), W, H)


@given(same_row_strips())
def test_no_cut_inside_a_strip(strips):
    cuts = physical_cuts(strips, W, H)
    for s in strips:
        for c in cuts:
            if c[1] == s.y:
                assert not (s.xa <= c[0] <= s.xb)  # a cut never lands inside strip copper


@given(
    st.integers(-50, 50),
    st.integers(-50, 50),
    st.integers(-50, 50),
    st.integers(-50, 50),
)
def test_rect_flip_is_involution(ax, ay, bx, by):
    r = Rect.of(ax, ay, bx, by)
    assert r.flip().flip() == r


@given(st.integers(-50, 50), st.integers(-50, 50))
def test_point_flip_is_involution(x, y):
    assert flip_point(flip_point((x, y))) == (x, y)


@given(
    st.integers(1, 15),
    st.integers(1, 15),
    st.integers(0, 10),
    st.integers(0, 10),
)
def test_extending_strip_past_pins_keeps_net_length(x1, x2, left_pad, right_pad):
    # SPEC section 4.3 corollary: dead-end copper doesn't change the diameter.
    lo, hi = sorted((x1, x2))
    y = 5
    pins = [("A", "1"), ("B", "1")]
    pos = {("A", "1"): (lo, y), ("B", "1"): (hi, y)}
    tight = [Strip(y, lo, hi, "N")]
    extended = [Strip(y, max(1, lo - left_pad), min(W, hi + right_pad), "N")]
    assert net_length(pins, pos, tight, [], []) == net_length(pins, pos, extended, [], [])
