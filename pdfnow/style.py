"""Style extraction and PDF reconstruction.

Extract visual style metrics from scanned pages and rebuild PDFs
from edited text while preserving the original look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
import numpy as np

from .model import Document, Page, Block, Line


@dataclass
class PageStyle:
    """Visual style metrics extracted from a scanned page."""
    page_width_pt: float = 595.0     # A4 default
    page_height_pt: float = 842.0
    margin_left_pt: float = 72.0     # ~2.5cm
    margin_right_pt: float = 72.0
    margin_top_pt: float = 72.0
    margin_bottom_pt: float = 72.0
    body_font_size_pt: float = 11.0
    line_spacing: float = 1.2         # multiplier on font size
    paragraph_spacing_pt: float = 6.0
    font_name: str = "tiro"            # Times Roman (serif, standard for documents)
    text_align: str = "left"          # left, center, right, justify
    header_font_size_pt: float = 14.0
    header_bold: bool = True
    footer_font_size_pt: float = 8.0


def extract_style(page: Page) -> PageStyle:
    """Analyze a page's OCR blocks to infer visual style metrics.

    Uses word bounding boxes to estimate font sizes, margins,
    line spacing, and alignment.
    """
    style = PageStyle()

    if not page.blocks:
        return style

    # Older project files may not have layout labels yet.
    if not any(block.label for block in page.blocks):
        analyze_layout(page)

    body_blocks = [block for block in page.blocks if block.label == "body"]
    analysis_blocks = body_blocks or page.blocks

    # Style metrics must describe the main text, not stamps or page numbers.
    all_words = [
        w for block in analysis_blocks
        for line in block.lines
        for w in line.words
    ]
    if not all_words:
        return style

    all_lines = [
        line for block in analysis_blocks
        for line in block.lines
    ]
    all_lines.sort(key=lambda line: (line.bbox.y0, line.bbox.x0))

    # Margins: min/max x and y of all words
    min_x = min(w.bbox.x0 for w in all_words)
    max_x = max(w.bbox.x1 for w in all_words)
    min_y = min(w.bbox.y0 for w in all_words)
    max_y = max(w.bbox.y1 for w in all_words)

    # Page dimensions from the page object (image pixels at 300 DPI)
    page_w_px = page.width or (max_x + min_x)
    page_h_px = page.height or (max_y + min_y)

    # Convert to points (300 DPI → 72 DPI)
    scale = 72.0 / 300.0
    style.page_width_pt = page_w_px * scale
    style.page_height_pt = page_h_px * scale
    style.margin_left_pt = min_x * scale
    style.margin_right_pt = (page_w_px - max_x) * scale
    style.margin_top_pt = min_y * scale
    style.margin_bottom_pt = (page_h_px - max_y) * scale

    # Font size: use lower-quartile word height (body text without ascenders)
    # Tesseract bboxes include ~15-20% padding; compensate with 1.15 factor
    heights = sorted(w.bbox.height for w in all_words)
    n = len(heights)
    median_height = heights[n // 2]
    p25_height = heights[n // 4] if n >= 4 else median_height
    style.body_font_size_pt = round(p25_height * scale * 1.15, 1)

    # Line spacing: average distance between consecutive lines
    if len(all_lines) >= 2:
        gaps = []
        for i in range(len(all_lines) - 1):
            gap = all_lines[i + 1].bbox.y0 - all_lines[i].bbox.y1
            if 0 < gap < median_height * 5:  # filter out paragraph breaks
                gaps.append(gap)
        if gaps:
            avg_gap = sum(gaps) / len(gaps) * scale
            style.line_spacing = 1.0 + (avg_gap / style.body_font_size_pt)
            style.line_spacing = max(1.0, min(style.line_spacing, 2.0))

    # Paragraph spacing: detect large gaps between lines
    if len(all_lines) >= 2:
        big_gaps = []
        for i in range(len(all_lines) - 1):
            gap = all_lines[i + 1].bbox.y0 - all_lines[i].bbox.y1
            if gap > median_height * 2.5:
                big_gaps.append(gap)
        if big_gaps:
            style.paragraph_spacing_pt = (sum(big_gaps) / len(big_gaps)) * scale

    # Alignment: compare left edges of lines
    left_edges = [line.bbox.x0 for line in all_lines]
    left_variance = np.std(left_edges) if len(left_edges) > 1 else 0
    if left_variance < page_w_px * 0.02:
        style.text_align = "left"
    else:
        right_edges = [line.bbox.x1 for line in all_lines]
        # Check if centered: left and right margins are similar
        avg_left_margin = sum(left_edges) / len(left_edges)
        avg_right_margin = sum(page_w_px - e for e in right_edges) / len(right_edges)
        if abs(avg_left_margin - avg_right_margin) < page_w_px * 0.05:
            style.text_align = "center"

    # Detect header: first block with larger font or bold
    if page.blocks:
        first_block = page.blocks[0]
        first_heights = [w.bbox.height for line in first_block.lines[:2] for w in line.words]
        if first_heights:
            first_avg = sum(first_heights) / len(first_heights)
            if first_avg > median_height * 1.2:
                style.header_font_size_pt = first_avg * scale * 0.9
                style.header_bold = True

    return style


def extract_structured_text(page: Page, *, only_body: bool = True) -> str:
    """Extract text preserving line breaks and paragraph structure.

    Paragraph breaks are detected by larger-than-normal gaps
    between consecutive lines.

    Args:
        page: The page to extract text from.
        only_body: If True, only extract text from blocks labeled "body"
                   (or unlabeled blocks, for backward compatibility).
                   If False, extract all blocks.
    """
    if not page.blocks:
        return ""

    if only_body and not any(block.label for block in page.blocks):
        analyze_layout(page)

    # Collect all lines across blocks, sorted by Y position
    all_lines: list[tuple[float, str]] = []
    for block in page.blocks:
        # Skip non-body blocks when filtering
        if only_body and block.label and block.label not in ("body", ""):
            continue
        for line in block.lines:
            all_lines.append((line.bbox.y0, line.text))

    all_lines.sort(key=lambda x: x[0])

    if not all_lines:
        return ""

    # Detect paragraph breaks
    included_blocks = [
        block for block in page.blocks
        if not only_body or block.label in ("body", "")
    ]
    heights = sorted(w.bbox.height for b in included_blocks for l in b.lines for w in l.words)
    median_height = heights[len(heights) // 2] if heights else 20

    result_lines: list[str] = []
    prev_y1 = 0.0

    for i, (y0, text) in enumerate(all_lines):
        if i > 0:
            gap = y0 - prev_y1
            if gap > median_height * 2.5:
                result_lines.append("")  # blank line = paragraph break

        result_lines.append(text)
        # Estimate bottom of this line
        for block in page.blocks:
            for line in block.lines:
                if line.bbox.y0 == y0 and line.text == text:
                    prev_y1 = line.bbox.y1
                    break

    return "\n".join(result_lines)


@dataclass
class PageLayout:
    """Detected layout regions of a scanned page."""
    main_text_bbox: tuple[float, float, float, float] | None = None
    header_bbox: tuple[float, float, float, float] | None = None
    sidebar_bbox: tuple[float, float, float, float] | None = None
    page_width: float = 0
    page_height: float = 0

    @property
    def main_text_rect(self) -> tuple[float, float, float, float] | None:
        return self.main_text_bbox


def analyze_layout(page: Page) -> PageLayout:
    """Analyze page blocks to detect the layout structure.

    Labels each block in-place as "header", "body", "sidebar", or "footer"
    and returns a PageLayout with region bounding boxes.

    The main text column is where we'll render the edited text;
    everything else (header, sidebar, footer) stays as-is from the scan.
    """
    layout = PageLayout()

    if not page.blocks:
        return layout

    layout.page_width = page.width
    layout.page_height = page.height
    pw = page.width

    # Classification thresholds
    SIDEBAR_X_THRESHOLD = pw * 0.70   # blocks starting past 70% width = sidebar
    SIDEBAR_SAFETY_MARGIN = 80        # px gap between text column and sidebar
    HEADER_Y_THRESHOLD = 450          # blocks ending above this = header area
    FOOTER_Y_THRESHOLD = page.height * 0.94  # blocks starting below 94% height = footer

    # Separate blocks by position and label them
    sidebar_blocks = []
    header_blocks = []
    footer_blocks = []
    body_blocks = []

    for block in page.blocks:
        if block.bbox.x0 > SIDEBAR_X_THRESHOLD:
            block.label = "sidebar"
            sidebar_blocks.append(block)
        elif block.bbox.y1 < HEADER_Y_THRESHOLD and block.bbox.x1 < SIDEBAR_X_THRESHOLD:
            block.label = "header"
            header_blocks.append(block)
        elif block.bbox.y0 > FOOTER_Y_THRESHOLD:
            block.label = "footer"
            footer_blocks.append(block)
        else:
            block.label = "body"
            body_blocks.append(block)

    if not body_blocks:
        return layout

    # Main text column: union of all body blocks
    text_left = min(b.bbox.x0 for b in body_blocks)
    text_top = min(b.bbox.y0 for b in body_blocks)

    # Bottom: stop before footer if present, otherwise use body bottom
    if footer_blocks:
        text_bottom = min(b.bbox.y0 for b in footer_blocks) - 10
    else:
        text_bottom = max(b.bbox.y1 for b in body_blocks)

    # Right edge: stop well before sidebar elements
    if sidebar_blocks:
        sidebar_left = min(b.bbox.x0 for b in sidebar_blocks)
        text_right = min(
            max(b.bbox.x1 for b in body_blocks),  # natural right edge of text
            sidebar_left - SIDEBAR_SAFETY_MARGIN  # but don't touch sidebar
        )
    else:
        text_right = max(b.bbox.x1 for b in body_blocks)

    layout.main_text_bbox = (text_left, text_top, text_right, text_bottom)

    # Header area
    if header_blocks:
        h_top = min(b.bbox.y0 for b in header_blocks)
        h_bottom = max(b.bbox.y1 for b in header_blocks)
        layout.header_bbox = (0, h_top, pw, h_bottom)

    # Sidebar area
    if sidebar_blocks:
        s_left = min(b.bbox.x0 for b in sidebar_blocks)
        s_top = min(b.bbox.y0 for b in sidebar_blocks)
        s_right = max(b.bbox.x1 for b in sidebar_blocks)
        s_bottom = max(b.bbox.y1 for b in sidebar_blocks)
        layout.sidebar_bbox = (s_left, s_top, s_right, s_bottom)

    return layout


def wrap_text_to_lines(
    text: str,
    max_width_pt: float,
    fontsize: float,
    fontname: str = "tiro",
) -> list[str]:
    """Wrap text into lines that fit within max_width_pt.

    Uses PyMuPDF font metrics so proportional fonts wrap at their real width.

    Args:
        text: Paragraph text (may contain internal \\n).
        max_width_pt: Available width in PDF points.
        fontsize: Font size in PDF points.
        fontname: PyMuPDF base font name.

    Returns:
        List of lines, each fitting within max_width_pt.
    """
    import fitz

    lines: list[str] = []

    for sub_para in text.split("\n"):
        words = sub_para.split()
        if not words:
            lines.append("")
            continue

        current_line = words[0]
        for word in words[1:]:
            candidate = current_line + " " + word
            if fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) <= max_width_pt:
                current_line = candidate
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line)

    return lines
