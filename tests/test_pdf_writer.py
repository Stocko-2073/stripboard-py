"""The dependency-free PDF writer that replaced PyFPDF.

These guard the two things the swap had to preserve exactly -- the operators that reach
the page content stream -- plus the structural validity and determinism of the output.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from stripboard.pdf import PdfDocument


def doc(**kwargs) -> PdfDocument:
    kwargs.setdefault("width_pt", 216.0)
    kwargs.setdefault("height_pt", 144.0)
    return PdfDocument(**kwargs)


def content_stream(data: bytes) -> str:
    m = re.search(rb"stream\n(.*?)endstream", data, re.DOTALL)
    assert m, "no content stream in output"
    return m.group(1).decode("latin-1")


# ---- content stream ------------------------------------------------------------------

def test_add_page_emits_line_cap_then_default_width():
    """The first two operators on every page, inherited from the PyFPDF behaviour."""
    d = doc()
    d.add_page()
    assert d._pages[0][:2] == ["2 J", "0.57 w"]


def test_out_appends_verbatim():
    d = doc()
    d.add_page()
    d.out("7.20000 0 0 7.20000 0 0 cm")
    assert d._pages[0][-1] == "7.20000 0 0 7.20000 0 0 cm"


def test_out_without_page_is_an_error():
    with pytest.raises(RuntimeError, match="no page open"):
        doc().out("1 0 0 1 0 0 cm")


@pytest.mark.parametrize(("args", "expected"), [
    ((255,), "1.000 G"),               # one argument -> greyscale
    ((0,), "0.000 G"),
    ((128,), "0.502 G"),
    ((0, 0, 0), "0.000 G"),            # black takes the greyscale path even spelled as RGB
    ((255, 0, 0), "1.000 0.000 0.000 RG"),
    ((16, 128, 255), "0.063 0.502 1.000 RG"),
])
def test_draw_colour_operators(args, expected):
    d = doc()
    d.add_page()
    d.set_draw_color(*args)
    assert d._pages[0][-1] == expected


def test_fill_colour_operators_are_lower_case():
    d = doc()
    d.add_page()
    d.set_fill_color(255, 0, 0)
    assert d._pages[0][-1] == "1.000 0.000 0.000 rg"
    d.set_fill_color(0)
    assert d._pages[0][-1] == "0.000 g"


def test_colour_is_re_emitted_even_when_unchanged():
    """No de-duplication: board rendering relies on the repeated operators."""
    d = doc()
    d.add_page()
    before = len(d._pages[0])
    d.set_draw_color(0)
    d.set_draw_color(0)
    d.set_draw_color(0)
    assert len(d._pages[0]) - before == 3


def test_colour_set_before_any_page_is_not_emitted_but_is_applied():
    d = doc()
    d.set_draw_color(255, 0, 0)
    d.add_page()
    # It carries onto the new page, after the cap and width.
    assert d._pages[0] == ["2 J", "0.57 w", "1.000 0.000 0.000 RG"]


def test_second_page_restores_the_graphics_state():
    d = doc()
    d.add_page()
    d.set_fill_color(10, 20, 30)
    d.add_page()
    assert d._pages[1] == ["2 J", "0.57 w", "0.039 0.078 0.118 rg"]


# ---- alpha / ExtGState ---------------------------------------------------------------

def test_set_alpha_allocates_and_selects_an_extgstate():
    d = doc()
    d.add_page()
    d.set_alpha(0.5)
    d.set_alpha(1.0)
    assert d._pages[0][-2:] == ["/GS1 gs", "/GS2 gs"]
    out = d.to_bytes().decode("latin-1")
    assert "/ExtGState <</GS1 " in out and "/GS2 " in out
    assert "/Type /ExtGState /ca 0.500 /CA 0.500 /BM /Normal" in out


def test_no_extgstate_resource_when_alpha_is_never_used():
    d = doc()
    d.add_page()
    assert "/ExtGState" not in d.to_bytes().decode("latin-1")


# ---- document structure --------------------------------------------------------------

def test_document_structure_and_xref_offsets_are_correct():
    d = doc()
    d.add_page()
    d.out("1 1 10 10 re f")
    data = d.to_bytes()

    assert data.startswith(b"%PDF-1.4\n")
    assert data.rstrip().endswith(b"%%EOF")

    startxref = int(re.search(rb"startxref\n(\d+)\n", data).group(1))
    assert data[startxref:startxref + 4] == b"xref"

    size = int(re.search(rb"/Size (\d+)", data).group(1))
    entries = re.findall(rb"^(\d{10}) (\d{5}) ([nf]) $", data[startxref:].decode("latin-1")
                         .encode("latin-1"), re.MULTILINE)
    assert len(entries) == size, "xref table must have one entry per object plus the free head"

    # Every recorded offset must actually point at that object's header.
    for i, (offset, _gen, kind) in enumerate(entries):
        if kind == b"f":
            continue
        assert data[int(offset):].startswith(f"{i} 0 obj".encode("latin-1"))


def test_mediabox_matches_the_requested_page_size():
    data = doc(width_pt=100 * 7.2, height_pt=80 * 7.2).__class__(
        width_pt=720.0, height_pt=576.0)
    data.add_page()
    assert b"/MediaBox [0 0 720.00 576.00]" in data.to_bytes()


def test_content_stream_length_is_accurate():
    d = doc()
    d.add_page()
    d.out("0 0 1 1 re f")
    data = d.to_bytes()
    declared = int(re.search(rb"<</Length (\d+)>>\nstream", data).group(1))
    assert declared == len(content_stream(data))


def test_multiple_pages_are_all_registered():
    d = doc()
    for _ in range(3):
        d.add_page()
    out = d.to_bytes().decode("latin-1")
    assert "/Type /Pages" in out and "/Count 3" in out
    assert out.count("/Type /Page ") == 3
    assert d.page == 3


def test_writing_with_no_pages_is_an_error():
    with pytest.raises(RuntimeError, match="no pages"):
        doc().to_bytes()


# ---- determinism ---------------------------------------------------------------------

def test_output_is_byte_reproducible_and_undated():
    """The reason golden-file testing is possible at all: no clock in the output."""
    def build():
        d = doc()
        d.add_page()
        d.set_draw_color(1, 2, 3)
        d.out("1 1 2 2 re f")
        return d.to_bytes()

    assert build() == build()
    assert b"/CreationDate" not in build()


def test_creation_date_is_written_when_supplied():
    d = doc(creation_date=dt.datetime(2026, 9, 3, 12, 30, 45))
    d.add_page()
    assert b"/CreationDate (D:20260903123045)" in d.to_bytes()


def test_producer_can_be_omitted():
    d = doc(producer=None)
    d.add_page()
    assert b"/Producer" not in d.to_bytes()


def test_text_strings_escape_pdf_delimiters():
    d = doc(producer=r"a(b)c\d")
    d.add_page()
    assert rb"/Producer (a\(b\)c\\d)" in d.to_bytes()


# ---- file output ---------------------------------------------------------------------

def test_output_writes_the_file_and_creates_parents(tmp_path):
    d = doc()
    d.add_page()
    d.out("0 0 1 1 re f")
    target = d.output(tmp_path / "nested" / "deeper" / "board.pdf")
    assert target.exists()
    assert target.read_bytes() == d.to_bytes()
