"""Row-letter coordinates.

Boards are addressed on a 1-based integer grid where rows may be written as letters
(`'A'` == 1 ... `'Z'` == 26) or as plain ints. Both spellings must agree everywhere,
because board files mix them freely.
"""

from __future__ import annotations

import pytest

from stripboard import parse_row


@pytest.mark.parametrize(("letter", "index"), [
    ("A", 1), ("B", 2), ("M", 13), ("Y", 25), ("Z", 26),
])
def test_row_letters_map_to_one_based_indices(board, letter, index):
    assert board.row(letter) == index


def test_row_passes_ints_through_unchanged(board):
    for n in (1, 5, 26, 40):
        assert board.row(n) == n


def test_row_is_idempotent(board):
    """Coercing an already-coerced row must not shift it -- this is applied repeatedly."""
    assert board.row(board.row("K")) == board.row("K")


@pytest.mark.parametrize(("height", "expected"), [
    ("A", 1), ("K", 11), ("Z", 26), (1, 1), (11, 11), (26, 26), (40, 40),
])
def test_rows_accepts_letters_and_ints(height, expected):
    """`parse_row` sizes a board from the same two spellings that `row` accepts."""
    assert parse_row(height) == expected


def test_board_height_is_stored_coerced(make_board):
    """A board built with a letter height reports an integer row count."""
    assert make_board(18, "Z").board_height == 26
    assert make_board(13, "K").board_height == 11


def test_board_width_is_stored_verbatim(make_board):
    assert make_board(13, "K").board_width == 13
