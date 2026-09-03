"""The `project()` driver: what gets rendered, and how many times.

`project()` is the whole per-board main block encapsulated. Its subtlety is that it
invokes `draw(sb)` **more than once** -- once per view on the build sheet, again on a
fresh black-and-white board for the label, again for the stroke capture that feeds the
g-code. Anything stateful in a board file has to survive that, and the autoroute cache
exists precisely so the solver does not re-run for each pass.
"""

from __future__ import annotations

import os

import pytest

from stripboard import project


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """project() writes relative to the working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def counting_draw():
    """A trivial board that records how many times it was drawn."""
    calls = []

    def draw(sb):
        calls.append(sb)
        sb.text(1, "A", "T")
        sb.led(4, "C")
    return draw, calls


class TestOutputFiles:
    def test_design_mode_writes_one_pdf(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=True, report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == ["b.pdf"]

    def test_build_mode_writes_one_pdf(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False, report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == ["b.pdf"]

    def test_label_adds_a_label_pdf_in_build_mode(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                label=True, report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == ["b-label.pdf", "b.pdf"]

    def test_label_is_not_rendered_in_design_mode(self, in_tmp):
        """Design mode is the fast iteration path, so it skips the build artifacts."""
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=True,
                label=True, report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == ["b.pdf"]

    def test_label_accepts_a_filename(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                label="custom.pdf", report=False)
        assert (in_tmp / "custom.pdf").exists()

    def test_label_accepts_an_options_dict(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                label=dict(name="d.pdf", page=(20, 20), width=10, height="H"),
                report=False)
        assert (in_tmp / "d.pdf").exists()

    def test_gcode_adds_nc_in_either_mode(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=True,
                gcode=True, report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == ["b.nc", "b.pdf"]

    def test_gcode_dict_can_also_emit_svg(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=True,
                gcode=dict(svg=True), report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == ["b.nc", "b.pdf", "b.svg"]

    def test_everything_at_once(self, in_tmp):
        draw, _ = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                label=True, gcode=True, report=False)
        assert sorted(p.name for p in in_tmp.iterdir()) == [
            "b-label.pdf", "b.nc", "b.pdf"]


class TestDrawInvocations:
    def test_design_mode_draws_once(self, in_tmp):
        draw, calls = counting_draw()
        project(draw, name="b", width=12, height="K", designing=True, report=False)
        assert len(calls) == 1

    def test_build_mode_draws_three_times_for_the_triptych(self, in_tmp):
        draw, calls = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False, report=False)
        assert len(calls) == 3, "FRONT, BACK and DESIGN each re-run draw()"

    def test_label_adds_a_fourth_pass_on_a_fresh_board(self, in_tmp):
        draw, calls = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                label=True, report=False)
        assert len(calls) == 4
        assert calls[-1] is not calls[0], "the label renders on its own StripBoard"
        assert calls[-1].black_and_white is True

    def test_gcode_adds_a_capture_pass(self, in_tmp):
        draw, calls = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                label=True, gcode=True, report=False)
        assert len(calls) == 5


class TestSizing:
    def test_height_accepts_a_row_letter_or_an_int(self, in_tmp):
        draw, _ = counting_draw()
        a = project(draw, name="a", width=12, height="K", designing=True, report=False)
        b = project(draw, name="b", width=12, height=11, designing=True, report=False)
        assert a.board_height == b.board_height == 11

    def test_page_sizes_are_derived_from_the_board(self, in_tmp):
        draw, _ = counting_draw()
        sb = project(draw, name="b", width=12, height="K", designing=True, report=False)
        assert (sb.page_width, sb.page_height) == (12 + 12, 11 + 10)

    def test_page_sizes_can_be_overridden(self, in_tmp):
        draw, _ = counting_draw()
        sb = project(draw, name="b", width=12, height="K", designing=True,
                     preview_page=(40, 30), report=False)
        assert (sb.page_width, sb.page_height) == (40, 30)

    def test_builds_stacks_several_boards_on_one_sheet(self, in_tmp):
        draw, calls = counting_draw()
        project(draw, name="b", width=12, height="K", designing=False,
                builds=[{"y": 0}, {"y": 30}], report=False)
        assert len(calls) == 6, "two board groups x three views"


def test_returns_the_primary_board(in_tmp):
    draw, calls = counting_draw()
    sb = project(draw, name="b", width=12, height="K", designing=True, report=False)
    assert sb is calls[0]


def test_report_is_a_noop_for_a_hand_routed_board(in_tmp, capsys):
    draw, _ = counting_draw()
    project(draw, name="b", width=12, height="K", designing=True, report=True)
    assert capsys.readouterr().out == "", "nothing to report without a netlist"
