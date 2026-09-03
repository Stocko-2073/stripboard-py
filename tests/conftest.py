"""Shared fixtures for the stripboard test suite."""

from __future__ import annotations

import pytest

from stripboard import StripBoard

# A board big enough for every footprint under test, small enough to solve quickly.
BOARD_W = 18
BOARD_H = "Z"


@pytest.fixture
def board():
    """A started board, ready for part builders and wiring calls."""
    sb = StripBoard(page_width=30, page_height=36)
    sb.begin_board(BOARD_W, BOARD_H, show_strips=True, at=(0, 0), show_traces=True, title="T")
    return sb


@pytest.fixture
def make_board():
    """Factory for boards of a specific size, when the default 18xZ does not fit."""
    def _make(width=BOARD_W, height=BOARD_H, *, page=(30, 36), title="T", **kwargs):
        sb = StripBoard(page_width=page[0], page_height=page[1])
        sb.begin_board(width, height, show_strips=True, at=(0, 0), show_traces=True,
                       title=title, **kwargs)
        return sb
    return _make
