"""Test suite for PdfNow core functionality.

Tests the critical paths: searchable text export, overflow detection,
sidebar filtering, line wrapping, and paragraph structure preservation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from pdfnow.model import BBox, Block, Document, Line, Page, Word
from pdfnow.export import export_searchable_pdf
from pdfnow.style import extract_style, extract_structured_text, wrap_text_to_lines
from pdfnow.ocr import TesseractEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_word(text: str, x0: float, y0: float, x1: float, y1: float,
               confidence: float = 0.9) -> Word:
    return Word(text=text, bbox=BBox(x0, y0, x1, y1), confidence=confidence)


def _make_line(words: list[Word]) -> Line:
    return Line(words=words)


def _make_block(lines: list[Line], label: str = "",
                replacement_text: str | None = None,
                deleted: bool = False) -> Block:
    bbox = BBox(
        x0=min(l.bbox.x0 for l in lines if l.words),
        y0=min(l.bbox.y0 for l in lines if l.words),
        x1=max(l.bbox.x1 for l in lines if l.words),
        y1=max(l.bbox.y1 for l in lines if l.words),
    )
    return Block(
        bbox=bbox, lines=lines, label=label,
        replacement_text=replacement_text, deleted=deleted,
    )


def _make_page(blocks: list[Block], number: int = 1,
               width: float = 2481, height: float = 3508) -> Page:
    return Page(number=number, width=width, height=height, blocks=blocks)


# ---------------------------------------------------------------------------
# Test 1: searchable PDF actually contains text
# ---------------------------------------------------------------------------

def test_searchable_text_written():
    """insert_text must write words that can be read back from the PDF."""
    words = [
        _make_word("Repertorio", 321, 384, 561, 433),
        _make_word("n.", 576, 396, 616, 421),
        _make_word("1182", 630, 396, 730, 421),
    ]
    line = _make_line(words)
    block = _make_block([line], label="body")
    page = _make_page([block])
    doc = Document(source_path="test.pdf", pages=[page])

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.pdf"
        pdf_path, warnings = export_searchable_pdf(doc, out)

        assert pdf_path.exists()
        # No overflow expected — words are normal size
        assert warnings == []

        # Read back text from the generated PDF
        import fitz
        pdf = fitz.open(str(pdf_path))
        full_text = ""
        for p in pdf:
            full_text += p.get_text()
        pdf.close()

        # All three words must be present and selectable
        assert "Repertorio" in full_text
        assert "n." in full_text
    assert "1182" in full_text


def test_replacement_text_is_searchable():
    """A structurally replaced main block must be present in the text layer."""
    original = _make_line([_make_word("Originale", 300, 400, 600, 450)])
    block = Block(
        bbox=BBox(300, 400, 1800, 3000),
        lines=[original],
        label="body",
        replacement_text=(
            "COMPRAVENDITA\n\n"
            "Francesco Esposito vende l'intera quota ad Alessandro Ruggiero."
        ),
    )
    doc = Document(source_path="test.pdf", pages=[_make_page([block])])

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "replacement.pdf"
        pdf_path, warnings = export_searchable_pdf(doc, out)
        assert warnings == []

        import fitz
        with fitz.open(str(pdf_path)) as pdf:
            full_text = "".join(page.get_text() for page in pdf)

        assert "COMPRAVENDITA" in full_text
        assert "Francesco Esposito" in full_text
        assert "Alessandro Ruggiero" in full_text


# ---------------------------------------------------------------------------
# Test 2: overflow detection
# ---------------------------------------------------------------------------

def test_no_silent_overflow():
    """Block replacement text that doesn't fit must produce a warning."""
    # Tiny block (5x5 px at 300 DPI → ~1.2x1.2 pt)
    tiny_line = _make_line([_make_word("X", 0, 0, 5, 5)])
    tiny_block = Block(
        bbox=BBox(0, 0, 5, 5),
        lines=[tiny_line],
        replacement_text="This is a very long replacement text that cannot possibly fit in 5 pixels",
    )
    page = _make_page([tiny_block])
    doc = Document(source_path="test.pdf", pages=[page])

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.pdf"
        _, warnings = export_searchable_pdf(doc, out)

        # Must have at least one overflow warning
        assert len(warnings) > 0, "Expected overflow warning, got none"
        assert any("exceeds" in w for w in warnings)


def test_normal_block_no_false_overflow():
    """Normal-sized blocks should NOT produce overflow warnings."""
    words = [_make_word("Hello", 100, 100, 200, 130)]
    block = _make_block([_make_line(words)])
    page = _make_page([block])
    doc = Document(source_path="test.pdf", pages=[page])

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.pdf"
        _, warnings = export_searchable_pdf(doc, out)
        assert warnings == [], f"Unexpected warnings: {warnings}"


# ---------------------------------------------------------------------------
# Test 3: sidebar excluded from body text
# ---------------------------------------------------------------------------

def test_sidebar_not_in_body_text():
    """extract_structured_text must exclude blocks labeled 'sidebar'."""
    body_words = [_make_word("Atto", 100, 500, 200, 530),
                  _make_word("Notarile", 220, 500, 380, 530)]
    sidebar_words = [_make_word("Timbro", 2000, 500, 2200, 530)]

    body_block = _make_block([_make_line(body_words)], label="body")
    sidebar_block = _make_block([_make_line(sidebar_words)], label="sidebar")

    page = _make_page([body_block, sidebar_block])

    text = extract_structured_text(page, only_body=True)

    assert "Atto" in text
    assert "Notarile" in text
    assert "Timbro" not in text, "Sidebar text leaked into body extraction"


def test_unlabeled_legacy_page_is_classified_automatically():
    """Old JSON projects with empty labels must still exclude the sidebar."""
    body = _make_block([_make_line([_make_word("Corpo", 300, 500, 500, 540)])])
    sidebar = _make_block([_make_line([_make_word("Timbro", 2000, 500, 2200, 540)])])
    page = _make_page([body, sidebar])

    text = extract_structured_text(page)

    assert "Corpo" in text
    assert "Timbro" not in text
    assert body.label == "body"
    assert sidebar.label == "sidebar"


def test_style_ignores_sidebar_and_footer():
    """Body style metrics must not be distorted by peripheral blocks."""
    body_lines = [
        _make_line([_make_word("Riga", 300, 500, 500, 540)]),
        _make_line([_make_word("Due", 300, 570, 480, 610)]),
    ]
    body = _make_block(body_lines, label="body")
    sidebar = _make_block(
        [_make_line([_make_word("Timbro", 2200, 100, 2400, 150)])],
        label="sidebar",
    )
    footer = _make_block(
        [_make_line([_make_word("1", 1200, 3450, 1220, 3480)])],
        label="footer",
    )

    style = extract_style(_make_page([body, sidebar, footer]))

    assert style.margin_left_pt == pytest.approx(300 * 72 / 300)
    assert style.margin_right_pt == pytest.approx((2481 - 500) * 72 / 300)
    assert style.margin_top_pt == pytest.approx(500 * 72 / 300)


def test_sidebar_included_when_only_body_false():
    """With only_body=False, sidebar text must be included."""
    body_words = [_make_word("Body", 100, 100, 200, 130)]
    sidebar_words = [_make_word("Side", 2000, 100, 2100, 130)]

    body_block = _make_block([_make_line(body_words)], label="body")
    sidebar_block = _make_block([_make_line(sidebar_words)], label="sidebar")

    page = _make_page([body_block, sidebar_block])

    text = extract_structured_text(page, only_body=False)

    assert "Body" in text
    assert "Side" in text


# ---------------------------------------------------------------------------
# Test 4: line wrapping
# ---------------------------------------------------------------------------

def test_wrap_text_to_lines_fits_width():
    """Wrapped lines must not exceed the character budget."""
    text = "Il signor Francesco Esposito dichiara di vendere l'immobile"
    max_width_pt = 200.0
    fontsize = 10.0

    lines = wrap_text_to_lines(text, max_width_pt, fontsize)

    import fitz
    for line in lines:
        assert fitz.get_text_length(line, fontname="tiro", fontsize=fontsize) <= max_width_pt


def test_wrap_text_preserves_all_words():
    """All words from the input must appear in the output."""
    text = "uno due tre quattro cinque sei sette otto nove dieci"
    max_width_pt = 100.0
    fontsize = 10.0

    lines = wrap_text_to_lines(text, max_width_pt, fontsize)
    reconstructed = " ".join(lines)

    assert "uno" in reconstructed
    assert "dieci" in reconstructed
    # Word count must match
    assert len(reconstructed.split()) == len(text.split())


def test_wrap_text_empty_lines():
    """Empty lines (\\n\\n inside a paragraph) must be preserved."""
    text = "Prima riga\n\nTerza riga"
    lines = wrap_text_to_lines(text, 500, 10)

    # Should have: "Prima riga", "", "Terza riga"
    assert lines[0] == "Prima riga"
    assert "" in lines
    assert "Terza riga" in lines


# ---------------------------------------------------------------------------
# Test 5: paragraph structure preserved
# ---------------------------------------------------------------------------

def test_paragraph_count_preserved():
    """Blocks separated by large gaps must produce separate paragraphs."""
    # Three blocks at y positions far apart (gap > 2.5x median height)
    w1 = _make_word("Paragrafo", 100, 100, 250, 130)   # height=30
    w2 = _make_word("Secondo", 100, 400, 250, 430)      # gap=270, height=30
    w3 = _make_word("Terzo", 100, 700, 200, 730)        # gap=270, height=30

    b1 = _make_block([_make_line([w1])], label="body")
    b2 = _make_block([_make_line([w2])], label="body")
    b3 = _make_block([_make_line([w3])], label="body")

    page = _make_page([b1, b2, b3])
    text = extract_structured_text(page)

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    assert len(paragraphs) == 3, \
        f"Expected 3 paragraphs, got {len(paragraphs)}: {paragraphs!r}"


# ---------------------------------------------------------------------------
# Model serialization round-trip
# ---------------------------------------------------------------------------

def test_model_round_trip():
    """Document → JSON → Document must preserve all data."""
    words = [_make_word("Test", 10, 20, 50, 45, confidence=0.85)]
    line = _make_line(words)
    block = _make_block([line], label="body")
    page = _make_page([block])
    doc = Document(source_path="source.pdf", pages=[page],
                   metadata={"ocr_lang": "ita"})

    data = doc.to_dict()
    reloaded = Document.from_dict(data)

    assert reloaded.source_path == "source.pdf"
    assert reloaded.metadata["ocr_lang"] == "ita"
    assert reloaded.total_words == 1
    w = reloaded.pages[0].blocks[0].lines[0].words[0]
    assert w.text == "Test"
    assert w.confidence == 0.85
    assert w.bbox.x0 == 10


def test_word_correction_round_trip():
    """Corrected text and status must survive serialization."""
    w = _make_word("sbagliato", 0, 0, 100, 30)
    w.corrected_text = "corretto"
    w.status = w.status.__class__("corrected")  # CorrectionStatus.CORRECTED

    d = w.to_dict()
    w2 = Word.from_dict(d)

    assert w2.text == "sbagliato"
    assert w2.corrected_text == "corretto"
    assert w2.display_text == "corretto"
    assert w2.status.value == "corrected"


def test_tesseract_decimal_confidence():
    """Tesseract may return confidence values as decimal strings."""
    data = {
        "text": ["test"], "conf": ["96.123"],
        "block_num": [1], "par_num": [1], "line_num": [1],
        "left": [0], "top": [0], "width": [10], "height": [10],
    }

    blocks = TesseractEngine()._parse_hocr_data(data, (100, 100))

    assert blocks[0].lines[0].words[0].confidence == pytest.approx(0.96123)
