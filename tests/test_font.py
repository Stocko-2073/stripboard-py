"""The built-in vector stroke font."""

from __future__ import annotations

import string

import pytest

from stripboard import StripBoard
from stripboard.font import VECTOR_CHARS

EM = 4  # nominal em box; descenders reach y=5


def test_covers_every_printable_ascii_character():
    missing = sorted(c for c in string.printable.strip() if c not in VECTOR_CHARS)
    assert missing == [], f"no glyph for {missing}"


def test_includes_the_micro_sign():
    """Component values need it -- 10uF is written 10µF on a silkscreen."""
    assert "µ" in VECTOR_CHARS


def test_space_is_blank():
    assert VECTOR_CHARS[" "] == []


@pytest.mark.parametrize("char", sorted(c for c in VECTOR_CHARS if c != " "))
def test_every_glyph_is_a_list_of_even_length_polylines(char):
    strokes = VECTOR_CHARS[char]
    assert strokes, f"{char!r} has no strokes"
    for stroke in strokes:
        assert len(stroke) >= 4, f"{char!r} has a stroke with fewer than two points"
        assert len(stroke) % 2 == 0, f"{char!r} has a stroke with a dangling coordinate"


@pytest.mark.parametrize("char", sorted(VECTOR_CHARS))
def test_glyphs_stay_within_the_em_box(char):
    for stroke in VECTOR_CHARS[char]:
        xs, ys = stroke[0::2], stroke[1::2]
        assert all(0 <= x <= EM for x in xs), f"{char!r} overflows horizontally"
        # Descenders (g j p q y |) reach one row below the box.
        assert all(0 <= y <= EM + 1.5 for y in ys), f"{char!r} overflows vertically"


def test_the_table_is_shared_not_rebuilt_per_board():
    a = StripBoard(page_width=10, page_height=10)
    b = StripBoard(page_width=10, page_height=10)
    assert a.vector_chars is b.vector_chars is VECTOR_CHARS


class TestDrawLetter:
    """draw_letter scales a glyph onto the hole grid and strokes it."""

    def board(self):
        sb = StripBoard(page_width=20, page_height=20, black_and_white=True)
        sb._cap_on = True
        sb.begin_view("LABEL", 12, "J", at=(0, 0))
        sb._cap_paths.clear()
        return sb

    def test_a_glyph_emits_one_path_per_stroke(self):
        sb = self.board()
        sb.draw_letter(2, 2, "H")
        assert len(sb._cap_paths) == len(VECTOR_CHARS["H"])

    def test_a_blank_glyph_emits_nothing(self):
        sb = self.board()
        sb.draw_letter(2, 2, " ")
        assert sb._cap_paths == []

    def test_an_unknown_character_warns_and_draws_nothing(self):
        """A stray character in a label must not abort the whole render."""
        from stripboard import MissingGlyphWarning
        sb = self.board()
        with pytest.warns(MissingGlyphWarning, match="No glyph"):
            sb.draw_letter(2, 2, "☃")
        assert sb._cap_paths == []

    def test_text_survives_an_unknown_character(self):
        from stripboard import MissingGlyphWarning
        sb = self.board()
        with pytest.warns(MissingGlyphWarning):
            sb.text(2, "B", "A☃B")
        assert sb._cap_paths, "the drawable characters are still drawn"

    def test_a_letter_moves_with_its_anchor(self):
        """Captured coordinates carry begin_board's centring offset, so compare deltas."""
        def origin(x, y):
            sb = self.board()
            sb.draw_letter(x, y, "I")
            pts = [p for path in sb._cap_paths for p in path]
            return min(p[0] for p in pts), min(p[1] for p in pts)

        base = origin(5, 3)
        moved = origin(8, 6)
        assert moved[0] - base[0] == pytest.approx(3.0, abs=1e-6)
        assert moved[1] - base[1] == pytest.approx(3.0, abs=1e-6)

    def test_a_letter_is_about_one_hole_wide(self):
        sb = self.board()
        sb.draw_letter(5, 3, "I")
        xs = [x for p in sb._cap_paths for x, _ in p]
        assert 0.5 <= max(xs) - min(xs) <= 1.0

    def test_x_scale_narrows_a_letter(self):
        wide, narrow = self.board(), self.board()
        wide.draw_letter(5, 3, "H")
        narrow.draw_letter(5, 3, "H", x_scale=0.5)

        def span(sb):
            xs = [x for p in sb._cap_paths for x, _ in p]
            return max(xs) - min(xs)

        assert span(narrow) == pytest.approx(span(wide) * 0.5, abs=1e-6)


class TestText:
    def test_text_advances_one_column_per_character(self):
        sb = StripBoard(page_width=30, page_height=20, black_and_white=True)
        sb._cap_on = True
        sb.begin_view("LABEL", 20, "J", at=(0, 0))
        sb._cap_paths.clear()
        sb.text(2, "B", "III")
        xs = [x for p in sb._cap_paths for x, _ in p]
        assert max(xs) - min(xs) == pytest.approx(2.8, abs=0.4), "three columns of I"

    def test_vtext_advances_downward(self):
        sb = StripBoard(page_width=30, page_height=30, black_and_white=True)
        sb._cap_on = True
        sb.begin_view("LABEL", 20, "T", at=(0, 0))
        sb._cap_paths.clear()
        sb.vtext(4, "B", "III")
        ys = [y for p in sb._cap_paths for _, y in p]
        assert max(ys) - min(ys) > 2.0
