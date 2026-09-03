"""Design-rule warnings.

These catch mistakes that are easy to make and hard to see on a rendered board: a hole
asked to hold two wire ends, a trace running into a hole marked not-connected, two nets
that turn out to be the same copper.
"""

from __future__ import annotations

import warnings

import pytest

from stripboard import (
    JumperConflictWarning,
    ShortCircuitWarning,
    StripboardWarning,
    TraceCollisionWarning,
)


def test_every_warning_shares_one_base_class():
    """So a board file can escalate or silence the whole family at once."""
    for cls in (JumperConflictWarning, ShortCircuitWarning, TraceCollisionWarning):
        assert issubclass(cls, StripboardWarning)
    assert issubclass(StripboardWarning, UserWarning)


class TestJumperConflict:
    def test_two_jumper_ends_in_one_hole_warn(self, board):
        board.jumper(3, "B", 3, "F")
        with pytest.warns(JumperConflictWarning, match=r"x=3 y=B"):
            board.jumper(3, "B", 8, "B")

    def test_distinct_holes_do_not_warn(self, board):
        with warnings.catch_warnings():
            warnings.simplefilter("error", StripboardWarning)
            board.jumper(3, "B", 3, "F")
            board.jumper(4, "B", 4, "F")
            board.jumper(5, "C", 9, "C")

    def test_the_message_names_the_hole_by_row_letter(self, board):
        board.jumper(7, "D", 7, "H")
        with pytest.warns(JumperConflictWarning) as caught:
            board.jumper(7, "H", 12, "H")
        assert "x=7 y=H" in str(caught[0].message)


class TestShortCircuit:
    def test_a_trace_reaching_a_not_connected_hole_warns(self, board):
        """nc() marks a hole as deliberately isolated; a trace arriving there is a bug."""
        board.nc(6, "C")
        board.jumper(3, "C", 3, "F")
        with pytest.warns(ShortCircuitWarning, match="Short circuit"):
            board.trace(3, "C")


class TestTraceCollision:
    def test_two_traces_meeting_on_one_strip_warn(self, board):
        """Tracing two nets that land on the same uncut strip means they are one net."""
        board.jumper(3, "C", 3, "F")
        board.trace(3, "C")
        with pytest.warns(TraceCollisionWarning, match="Trace collision"):
            board.trace(9, "C")


def test_warnings_can_be_escalated_to_errors(board):
    """The point of using warnings: a build can be made to fail on a DRC violation."""
    board.jumper(3, "B", 3, "F")
    with warnings.catch_warnings():
        warnings.simplefilter("error", StripboardWarning)
        with pytest.raises(JumperConflictWarning):
            board.jumper(3, "B", 8, "B")


def test_warnings_are_attributed_to_the_calling_board_file(board):
    """stacklevel must point at the caller's draw(), not inside the library."""
    board.jumper(3, "B", 3, "F")
    with pytest.warns(JumperConflictWarning) as caught:
        board.jumper(3, "B", 8, "B")
    assert caught[0].filename == __file__
