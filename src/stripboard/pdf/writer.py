"""A small, dependency-free PDF writer.

Replaces the PyFPDF dependency this library used to carry. That was only ever used as a
document container -- board rendering writes raw PDF content-stream operators through
:meth:`PdfDocument.out`, and all text is drawn with the built-in vector stroke font, so no
font machinery, text layout, or image support is needed.

Two behaviours are reproduced deliberately, because they land in the page content stream
and the rendered output must not change:

* :meth:`add_page` emits ``2 J`` (projecting square line cap) followed by the default
  line width ``0.57 w``.
* Colour setters emit ``%.3f G`` / ``%.3f %.3f %.3f RG`` (upper case for stroking, lower
  case for filling) on *every* call, with no de-duplication of unchanged colours.

Unlike PyFPDF, output is deterministic: there is no ``/CreationDate`` unless one is passed
explicitly, so identical drawing calls produce identical bytes. Content streams are never
compressed, which keeps them diffable and makes golden-file testing practical.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

__all__ = ["PdfDocument"]

# PyFPDF's default line width is 0.2 mm (0.567 pt); it reaches the stream as "0.57 w".
DEFAULT_LINE_WIDTH_PT = 0.567

_DEFAULT_DRAW_COLOR = "0.000 G"
_DEFAULT_FILL_COLOR = "0.000 g"


def _num(value: float) -> str:
    """Format a coordinate the way PDF wants it: no exponent, no trailing noise."""
    text = f"{value:.2f}"
    return text


class PdfDocument:
    """An uncompressed, single- or multi-page PDF built from raw content-stream lines.

    Args:
      width_pt, height_pt: page size in PostScript points (72 per inch).
      version: PDF version written in the header. 1.4 is the floor for ExtGState alpha.
      creation_date: stamped as ``/CreationDate`` when given. Left out by default so
        output is byte-reproducible.
      producer: stamped as ``/Producer``. Set to ``None`` to omit.
    """

    def __init__(
        self,
        *,
        width_pt: float,
        height_pt: float,
        version: str = "1.4",
        creation_date: _dt.datetime | None = None,
        producer: str | None = "stripboard",
    ) -> None:
        self.width_pt = float(width_pt)
        self.height_pt = float(height_pt)
        self.version = version
        self.creation_date = creation_date
        self.producer = producer
        self.line_width_pt = DEFAULT_LINE_WIDTH_PT

        self.draw_color = _DEFAULT_DRAW_COLOR
        self.fill_color = _DEFAULT_FILL_COLOR

        self._pages: list[list[str]] = []
        self._extgstates: list[tuple[float, float, str]] = []  # (ca, CA, blend mode)

    # ---- page + content -------------------------------------------------------------

    @property
    def page(self) -> int:
        """Number of pages started so far (1-based page numbering, 0 before the first)."""
        return len(self._pages)

    def add_page(self) -> None:
        """Begin a new page, re-establishing the graphics state on it.

        A PDF content stream starts from the default graphics state, so the line cap,
        line width and any non-default colours have to be re-emitted per page.
        """
        self._pages.append([])
        self.out("2 J")
        self.out(f"{self.line_width_pt:.2f} w")
        if self.draw_color != _DEFAULT_DRAW_COLOR:
            self.out(self.draw_color)
        if self.fill_color != _DEFAULT_FILL_COLOR:
            self.out(self.fill_color)

    def out(self, s: str) -> None:
        """Append a raw line to the current page's content stream."""
        if not self._pages:
            raise RuntimeError("no page open -- call add_page() first")
        self._pages[-1].append(s)

    # ---- graphics state -------------------------------------------------------------

    def set_draw_color(self, r: float, g: float = -1, b: float = -1) -> None:
        """Set the stroking colour. One argument means greyscale; 0,0,0 also means grey."""
        self.draw_color = self._color_op(r, g, b, upper=True)
        if self._pages:
            self.out(self.draw_color)

    def set_fill_color(self, r: float, g: float = -1, b: float = -1) -> None:
        """Set the filling colour. One argument means greyscale; 0,0,0 also means grey."""
        self.fill_color = self._color_op(r, g, b, upper=False)
        if self._pages:
            self.out(self.fill_color)

    @staticmethod
    def _color_op(r: float, g: float, b: float, *, upper: bool) -> str:
        """Build the PDF colour operator, matching PyFPDF's greyscale/RGB split exactly."""
        if (r == 0 and g == 0 and b == 0) or g == -1:
            return f"{r / 255.0:.3f} {'G' if upper else 'g'}"
        return (f"{r / 255.0:.3f} {g / 255.0:.3f} {b / 255.0:.3f} "
                f"{'RG' if upper else 'rg'}")

    def set_line_width(self, width_pt: float) -> None:
        """Set the default line width, in points, and emit it if a page is open."""
        self.line_width_pt = width_pt
        if self._pages:
            self.out(f"{width_pt:.2f} w")

    def set_alpha(self, alpha: float, bm: str = "Normal") -> None:
        """Set constant stroke and fill alpha via an ExtGState, and select it."""
        self._extgstates.append((alpha, alpha, bm))
        self.out(f"/GS{len(self._extgstates)} gs")

    # ---- serialization --------------------------------------------------------------

    def output(self, path: str | Path) -> Path:
        """Write the document to `path`, creating parent directories as needed."""
        target = Path(path)
        if target.parent != Path():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.to_bytes())
        return target

    def to_bytes(self) -> bytes:
        """Serialize the whole document.

        Object layout: 1 = Catalog, 2 = Pages, 3 = Resources, then one Page and one
        Contents stream per page, then the ExtGStates, then Info.
        """
        if not self._pages:
            raise RuntimeError("cannot write a PDF with no pages -- call add_page() first")

        n_pages = len(self._pages)
        first_page_obj = 4
        page_objs = [first_page_obj + 2 * i for i in range(n_pages)]
        gs_first = first_page_obj + 2 * n_pages
        gs_objs = [gs_first + i for i in range(len(self._extgstates))]
        info_obj = gs_first + len(self._extgstates)

        objects: dict[int, bytes] = {}

        kids = " ".join(f"{n} 0 R" for n in page_objs)
        objects[1] = self._dict(f"/Type /Catalog /Pages 2 0 R "
                                f"/OpenAction [{page_objs[0]} 0 R /FitH null] "
                                f"/PageLayout /OneColumn")
        objects[2] = self._dict(f"/Type /Pages /Kids [{kids}] /Count {n_pages}")

        gs_entries = " ".join(f"/GS{i + 1} {n} 0 R" for i, n in enumerate(gs_objs))
        resources = "/ProcSet [/PDF]"
        if gs_entries:
            resources += f" /ExtGState <<{gs_entries}>>"
        objects[3] = self._dict(resources)

        media = f"[0 0 {_num(self.width_pt)} {_num(self.height_pt)}]"
        for i, lines in enumerate(self._pages):
            page_obj = page_objs[i]
            content_obj = page_obj + 1
            objects[page_obj] = self._dict(
                f"/Type /Page /Parent 2 0 R /MediaBox {media} "
                f"/Resources 3 0 R /Contents {content_obj} 0 R"
            )
            body = ("\n".join(lines) + "\n").encode("latin-1")
            objects[content_obj] = (
                f"<</Length {len(body)}>>\nstream\n".encode("latin-1")
                + body
                + b"endstream"
            )

        for i, (ca, upper_ca, bm) in enumerate(self._extgstates):
            objects[gs_objs[i]] = self._dict(
                f"/Type /ExtGState /ca {ca:.3f} /CA {upper_ca:.3f} /BM /{bm}"
            )

        objects[info_obj] = self._dict(self._info())

        # Assemble the body, recording each object's byte offset for the xref table.
        out = bytearray(f"%PDF-{self.version}\n".encode("latin-1"))
        offsets: dict[int, int] = {}
        for num in sorted(objects):
            offsets[num] = len(out)
            out += f"{num} 0 obj\n".encode("latin-1")
            out += objects[num]
            out += b"\nendobj\n"

        startxref = len(out)
        count = info_obj + 1  # objects 1..info_obj, plus the free entry 0
        out += f"xref\n0 {count}\n".encode("latin-1")
        out += b"0000000000 65535 f \n"
        for num in range(1, info_obj + 1):
            out += f"{offsets[num]:010d} 00000 n \n".encode("latin-1")
        out += (
            f"trailer\n<</Size {count} /Root 1 0 R /Info {info_obj} 0 R>>\n"
            f"startxref\n{startxref}\n%%EOF\n"
        ).encode("latin-1")
        return bytes(out)

    def _info(self) -> str:
        parts = []
        if self.producer:
            parts.append(f"/Producer {self._text_string(self.producer)}")
        if self.creation_date is not None:
            stamp = self.creation_date.strftime("%Y%m%d%H%M%S")
            parts.append(f"/CreationDate {self._text_string('D:' + stamp)}")
        return " ".join(parts)

    @staticmethod
    def _dict(contents: str) -> bytes:
        return f"<<{contents}>>".encode("latin-1")

    @staticmethod
    def _text_string(s: str) -> str:
        """A PDF literal string, with the three characters that must be escaped."""
        escaped = s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        return f"({escaped})"
