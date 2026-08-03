"""Reflow pages 1-7 as one uniform text stream, then append annexes 11-13."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import html
import re
import sys

import fitz
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pdfnow.model import Document
from pdfnow.style import analyze_layout, extract_structured_text, wrap_text_to_lines


EXPORT = ROOT / "export"
PROJECT = EXPORT / "atto_13p.json"
PAGE1_TEXT = ROOT / "pagina1_v2.txt"
UNTOUCHED = EXPORT / "atto_searchable_unmod.pdf"
OUTPUT = EXPORT / "atto_finale_ripaginato.pdf"
STORY_LAYOUT = EXPORT / "_story_layout.pdf"

FONT_SIZE = 11.5
LINE_SPACING = 1.50
PARAGRAPH_GAP = 0.0
BALANCE_RESERVE_PT = 60.0
TEXT_LEFT = 320 * 72 / 300
TEXT_RIGHT = 1866 * 72 / 300
TEXT_TOP = 384 * 72 / 300
TEXT_BOTTOM = 3403 * 72 / 300
RENDER_DPI = 300

PUNCTUATION_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
    "\u00a0": " ",
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl",
})


def normalize_paragraph(raw: str) -> str:
    """Remove OCR line wrapping while preserving the words."""
    text = raw.translate(PUNCTUATION_MAP).strip()
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def collect_paragraphs(document: Document) -> list[str]:
    """Combine edited page 1 with the original body text from pages 2-7."""
    page_texts = [PAGE1_TEXT.read_text(encoding="utf-8")]
    for page_number in range(2, 8):
        page = document.pages[page_number - 1]
        analyze_layout(page)
        page_texts.append(extract_structured_text(page, only_body=True))

    def is_heading_line(line: str) -> bool:
        text = line.strip()
        return (
            bool(re.match(r"^Art\.\s*\d+", text, flags=re.IGNORECASE))
            or text.lower() in ("quale parte venditrice", "quale parte acquirente")
            or (text.isupper() and len(text) <= 80)
        )

    paragraphs: list[str] = []
    for page_text in page_texts:
        current_lines: list[str] = []

        def flush_current() -> None:
            if not current_lines:
                return
            paragraph = normalize_paragraph("\n".join(current_lines))
            current_lines.clear()
            if paragraph:
                paragraphs.append(paragraph)

        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                flush_current()
                continue
            if is_heading_line(line):
                flush_current()
                paragraphs.append(normalize_paragraph(line))
                continue
            current_lines.append(line)
        flush_current()
    return paragraphs


def paragraph_style(paragraph: str) -> tuple[str, float, int]:
    """Return font name, font size, and alignment for one paragraph."""
    text = paragraph.strip()
    if text.lower().startswith(("quale parte venditrice", "quale parte acquirente")):
        return "tiit", FONT_SIZE, 1
    if text.lower().startswith("il tutto censito"):
        return "tiit", FONT_SIZE, 0
    if re.match(r"^Art\.\s*\d+", text, flags=re.IGNORECASE):
        return "tibo", FONT_SIZE * 1.15, 1
    if text.isupper() and len(text) <= 80:
        return "tibo", FONT_SIZE * 1.15, 1
    return "tiro", FONT_SIZE, 0


def paragraph_class(paragraph: str) -> str:
    """Map semantic paragraph types to CSS classes."""
    text = paragraph.strip()
    if text.lower().startswith(("quale parte venditrice", "quale parte acquirente")):
        return "role"
    if text.lower().startswith("il tutto censito"):
        return "italic"
    if re.match(r"^Art\.\s*\d+", text, flags=re.IGNORECASE):
        return "heading"
    if text.isupper() and len(text) <= 80:
        return "heading"
    return "body"


def write_story_layout(paragraphs: list[str]) -> int:
    """Lay out all paragraphs with PyMuPDF Story and return page count."""
    body = "".join(
        f'<p class="{paragraph_class(paragraph)}">{html.escape(paragraph)}</p>'
        for paragraph in paragraphs
    )
    css = f"""
        * {{ box-sizing: border-box; }}
        body {{
            font-family: serif;
            font-size: {FONT_SIZE}pt;
            line-height: {LINE_SPACING};
            color: #000;
            margin: 0;
            padding: 0;
        }}
        p {{ margin: 0 0 {PARAGRAPH_GAP}pt 0; padding: 0; }}
        p.body {{ text-align: left; }}
        p.heading {{
            font-weight: bold;
            font-size: {FONT_SIZE * 1.15}pt;
            text-align: center;
            margin-top: 2pt;
            margin-bottom: 3pt;
            break-after: avoid;
        }}
        p.role {{ font-style: italic; text-align: center; }}
        p.italic {{ font-style: italic; text-align: left; }}
    """

    story = fitz.Story(f"<html><body>{body}</body></html>", user_css=css, em=FONT_SIZE)
    media_box = fitz.Rect(0, 0, 2481 * 72 / 300, 3508 * 72 / 300)
    writer = fitz.DocumentWriter(str(STORY_LAYOUT))
    page_count = 0
    more = 1
    while more:
        device = writer.begin_page(media_box)
        page_bottom = TEXT_BOTTOM - BALANCE_RESERVE_PT if page_count < 6 else TEXT_BOTTOM
        text_rect = fitz.Rect(TEXT_LEFT, TEXT_TOP, TEXT_RIGHT, page_bottom)
        more, _ = story.place(text_rect)
        story.draw(device)
        writer.end_page()
        page_count += 1
        if page_count > 7:
            writer.close()
            raise RuntimeError("Story layout exceeds the seven available text pages")
    writer.close()
    return page_count


def validate_story_layout(story_document: fitz.Document) -> None:
    """Reject layouts containing vertically overlapping text lines."""
    problems: list[str] = []
    for page_number, page in enumerate(story_document, start=1):
        lines = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                bbox = fitz.Rect(line["bbox"])
                text = "".join(span.get("text", "") for span in line.get("spans", []))
                if text.strip():
                    lines.append((bbox, text))
        lines.sort(key=lambda item: (item[0].y0, item[0].x0))
        for (first_box, first_text), (second_box, second_text) in zip(lines, lines[1:]):
            horizontal_overlap = min(first_box.x1, second_box.x1) - max(first_box.x0, second_box.x0)
            vertical_overlap = first_box.y1 - second_box.y0
            if horizontal_overlap > 2 and vertical_overlap > 0.75:
                problems.append(
                    f"page {page_number}: {first_text!r} overlaps {second_text!r} "
                    f"by {vertical_overlap:.1f}pt"
                )
    if problems:
        raise RuntimeError("Story overlap validation failed: " + "; ".join(problems[:5]))


def build_story_pages(document: Document, paragraphs: list[str]) -> fitz.Document:
    """Composite the Story output over cleaned original page backgrounds."""
    page_count = write_story_layout(paragraphs)
    if page_count != 7:
        raise RuntimeError(
            f"Story produced {page_count} pages; expected exactly 7. "
            "Adjust the global CSS typography before exporting."
        )

    story_document = fitz.open(STORY_LAYOUT)
    validate_story_layout(story_document)
    result = fitz.open()
    for page_number in range(1, 8):
        model_page = document.pages[page_number - 1]
        width = model_page.width * 72 / 300
        height = model_page.height * 72 / 300
        page = result.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=cleaned_background(model_page))
        page.show_pdf_page(page.rect, story_document, page_number - 1, overlay=True)
    story_document.close()
    return result


def cleaned_background(page) -> bytes:
    """Keep stamps and page furniture while clearing the complete body column."""
    if not page.image_path or not Path(page.image_path).exists():
        raise FileNotFoundError(f"Missing page image: {page.image_path}")

    with Image.open(page.image_path) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((315, 379, 1871, 3408), fill="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_vector_pages(document: Document, paragraphs: list[str]) -> fitz.Document:
    """Lay out the continuous text stream across original page backgrounds."""
    result = fitz.open()
    for page_number in range(1, 8):
        model_page = document.pages[page_number - 1]
        width = model_page.width * 72 / 300
        height = model_page.height * 72 / 300
        pdf_page = result.new_page(width=width, height=height)
        pdf_page.insert_image(pdf_page.rect, stream=cleaned_background(model_page))

    page_index = 0
    y = TEXT_TOP
    text_width = TEXT_RIGHT - TEXT_LEFT

    for paragraph_index, paragraph in enumerate(paragraphs):
        fontname, fontsize, align = paragraph_style(paragraph)
        line_height = fontsize * LINE_SPACING
        lines = wrap_text_to_lines(paragraph, text_width, fontsize, fontname)

        # Keep short headings together with at least one following line.
        minimum_height = line_height * (2 if align == 1 and len(lines) == 1 else 1)
        if y + minimum_height > TEXT_BOTTOM:
            page_index += 1
            y = TEXT_TOP

        for line in lines:
            if y + line_height > TEXT_BOTTOM:
                page_index += 1
                y = TEXT_TOP
            if page_index >= result.page_count:
                raise RuntimeError(
                    f"Text exceeds seven pages at paragraph {paragraph_index + 1}/{len(paragraphs)}"
                )

            baseline = y + line_height
            x = TEXT_LEFT
            if align == 1:
                width = fitz.get_text_length(line, fontname=fontname, fontsize=fontsize)
                x += max(0.0, (text_width - width) / 2)
            result[page_index].insert_text(
                fitz.Point(x, baseline),
                line,
                fontsize=fontsize,
                fontname=fontname,
                render_mode=0,
            )
            y += line_height

        y += PARAGRAPH_GAP

    print(
        f"Reflow: {len(paragraphs)} paragrafi distribuiti su "
        f"{page_index + 1} delle 7 pagine disponibili"
    )
    return result


def append_rasterized_page(target: fitz.Document, source_page: fitz.Page) -> None:
    """Convert one uniform vector page to a scan-like image plus hidden text."""
    text_dict = source_page.get_text("dict")
    matrix = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    pixmap = source_page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    image = image.filter(ImageFilter.GaussianBlur(0.25))
    image_buffer = BytesIO()
    image.save(image_buffer, format="JPEG", quality=92, subsampling=0, dpi=(300, 300))

    page = target.new_page(width=source_page.rect.width, height=source_page.rect.height)
    page.insert_image(page.rect, stream=image_buffer.getvalue())
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").translate(PUNCTUATION_MAP)
                origin = span.get("origin")
                if not text.strip() or not origin:
                    continue
                page.insert_text(
                    fitz.Point(*origin),
                    text,
                    fontsize=max(1.0, float(span.get("size", FONT_SIZE))),
                    fontname="helv",
                    render_mode=3,
                )


def main() -> None:
    document = Document.load(PROJECT)
    paragraphs = collect_paragraphs(document)
    vector_pages = build_story_pages(document, paragraphs)
    final = fitz.open()

    for page in vector_pages:
        append_rasterized_page(final, page)
    vector_pages.close()

    # Annexes corresponding to original pages 11-13.
    with fitz.open(UNTOUCHED) as untouched:
        final.insert_pdf(untouched, from_page=3, to_page=5)

    final.set_metadata({
        "title": "Atto notarile - versione ripaginata uniforme",
        "producer": "PdfNow",
    })
    final.save(OUTPUT, garbage=4, deflate=True)
    final.close()

    with fitz.open(OUTPUT) as check:
        print(f"Creato {OUTPUT}: {check.page_count} pagine")
        print(f"Testo ricercabile: {sum(len(page.get_text()) for page in check)} caratteri")


if __name__ == "__main__":
    main()
