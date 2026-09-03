"""Affine transforms and the parallel capture CTM.

Rendering keeps two transformation stacks in step: the PDF's own (driven by `cm`
operators in the content stream) and a private copy used to record stroked geometry in
board-grid coordinates for the g-code and SVG exporters. If they drift, the PDF and the
laser output disagree -- and nothing else would catch it.
"""

from __future__ import annotations

import math

import pytest

from stripboard import StripBoard
from stripboard import transform as T

# ---- the pure matrix maths -----------------------------------------------------------

def test_identity_leaves_a_point_alone():
    assert T.apply(T.IDENTITY, 3.0, 4.0) == (3.0, 4.0)


def test_apply_follows_the_pdf_point_mapping():
    """x' = a*x + c*y + e, y' = b*x + d*y + f."""
    m = (2.0, 3.0, 5.0, 7.0, 11.0, 13.0)
    x, y = 1.5, -2.5
    assert T.apply(m, x, y) == (2.0 * x + 5.0 * y + 11.0, 3.0 * x + 7.0 * y + 13.0)


def test_translation_moves_a_point():
    assert T.apply(T.translation(10, -4), 1, 1) == (11, -3)


def test_scaling_scales_each_axis():
    assert T.apply(T.scaling(2, 3), 4, 5) == (8, 15)


def test_flip_y_negates_y_only():
    assert T.apply(T.FLIP_Y, 3, 4) == (3, -4)


def test_flip_x_negates_x_only():
    assert T.apply(T.FLIP_X, 3, 4) == (-3, 4)


def test_flips_are_involutions():
    for flip in (T.FLIP_X, T.FLIP_Y):
        assert T.compose(flip, flip) == T.IDENTITY


def test_quarter_rotation_maps_x_onto_y():
    r = T.rotation(math.cos(math.pi / 2), math.sin(math.pi / 2))
    x, y = T.apply(r, 1.0, 0.0)
    assert (x, y) == pytest.approx((0.0, 1.0), abs=1e-12)


def test_four_quarter_rotations_return_to_start():
    q = T.rotation(math.cos(math.pi / 2), math.sin(math.pi / 2))
    m = T.IDENTITY
    for _ in range(4):
        m = T.compose(q, m)
    assert T.apply(m, 7.0, -3.0) == pytest.approx((7.0, -3.0), abs=1e-12)


def test_compose_applies_the_operand_first():
    """PDF `cm` pre-multiplies, so the newest transform sits nearest the geometry."""
    scale_then_move = T.compose(T.scaling(2, 2), T.translation(10, 0))
    # The point is scaled first, then translated.
    assert T.apply(scale_then_move, 1, 1) == (12, 2)


def test_compose_with_identity_is_a_no_op():
    m = T.compose(T.scaling(3, 5), T.translation(1, 2))
    assert T.compose(T.IDENTITY, m) == m
    assert T.compose(m, T.IDENTITY) == m


def test_compose_is_associative():
    a, b, c = T.scaling(2, 3), T.translation(4, 5), T.rotation(0.6, 0.8)
    left = T.compose(T.compose(a, b), c)
    right = T.compose(a, T.compose(b, c))
    assert left == pytest.approx(right, abs=1e-12)


# ---- the capture CTM stack on a live board -------------------------------------------

def ctm(sb):
    return sb._cap_ctm[-1]


def test_push_and_pop_restore_the_previous_frame():
    sb = StripBoard(page_width=20, page_height=20)
    sb._cap_ctm = [T.IDENTITY]
    sb._push()
    sb._translate(5, 7)
    assert ctm(sb) != T.IDENTITY
    sb._pop()
    assert ctm(sb) == T.IDENTITY


def test_pop_never_empties_the_stack():
    """An unbalanced pop must not leave the board with no current transform."""
    sb = StripBoard(page_width=20, page_height=20)
    for _ in range(5):
        sb._pop()
    assert len(sb._cap_ctm) == 1


def test_nested_transforms_accumulate():
    sb = StripBoard(page_width=20, page_height=20)
    sb._cap_ctm = [T.IDENTITY]
    sb._translate(1, 2)
    sb._scale(2)
    # Scale is innermost, so the point is doubled and then offset.
    assert sb._cap_pt(3, 4) == (1 + 6, 2 + 8)


def test_begin_board_zeroes_the_capture_frame():
    """The base page transforms must drop out, so captures land in hole units.

    __init__ applies a 7.2x scale, a Y flip and a page translate to get into PDF user
    space. begin_board resets the capture CTM afterwards so recorded geometry stays on
    the board grid, which is what the mm-based exporters expect.
    """
    sb = StripBoard(page_width=30, page_height=30)
    assert ctm(sb) != T.IDENTITY, "page setup transforms should have accumulated"
    sb.begin_board(10, "J", title="")
    # begin_board re-centres the board, so the frame is a pure translation: no scale,
    # no flip -- one grid step still measures one unit.
    a, b, c, d, _e, _f = ctm(sb)
    assert (a, b, c, d) == (1.0, 0.0, 0.0, 1.0)


def test_captured_geometry_is_in_hole_units():
    sb = StripBoard(page_width=30, page_height=30, black_and_white=True)
    sb._cap_on = True
    sb.begin_view("LABEL", 10, "J", at=(0, 0))
    sb.end_board()
    xs = [x for path in sb._cap_paths for x, _ in path]
    ys = [y for path in sb._cap_paths for _, y in path]
    # The board outline spans (width+1) x (height+1) holes.
    assert max(xs) - min(xs) == pytest.approx(11.0, abs=1e-6)
    assert max(ys) - min(ys) == pytest.approx(11.0, abs=1e-6)


def test_capture_ignores_short_paths():
    sb = StripBoard(page_width=20, page_height=20)
    sb._cap_on = True
    before = len(sb._cap_paths)
    sb._cap_add([(0, 0)])
    assert len(sb._cap_paths) == before, "a single point is not a stroke"
