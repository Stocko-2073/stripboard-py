"""Minimal PDF output for stripboard.

Board rendering emits raw PDF content-stream operators directly, so the only PDF
machinery needed is a document container: page setup, colour operators, alpha via
ExtGState, and serialization. :class:`PdfDocument` provides exactly that in a few hundred
lines, which is why this package has no third-party runtime dependencies.
"""

from __future__ import annotations

from .writer import PdfDocument

__all__ = ["PdfDocument"]
