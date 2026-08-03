"""PDF export — generate output PDFs preserving the visual style of the original.

The core technique for "searchable PDF with style preservation":
- Layer 1 (bottom): the original scanned page image
- Layer 2 (top): invisible text positioned exactly over each word

This gives you a PDF that looks identical to the original but has
selectable/searchable text — with corrections applied.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .model import CorrectionStatus, Document, Page, Line, Word, Block


def _wrap_text_measured(text: str, max_width: float, fontsize: float, fontname: str = "helv") -> list[str]:
    """Wrap text using PyMuPDF's real font metrics."""
    import fitz

    lines: list[str] = []
    for source_line in text.split("\n"):
        words = source_line.split()
        if not words:
            lines.append("")
            continue

        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _estimate_text_height(
    text: str,
    box_width_pt: float,
    fontsize: float,
    line_spacing: float = 1.35,
) -> float:
    """Estimate the height needed to fit text in a given width.

    Uses a rough character-width heuristic: avg char ≈ 0.5 × fontsize.
    Returns the estimated height in PDF points.
    """
    chars_per_line = max(1, int(box_width_pt / (fontsize * 0.5)))
    lines = 0
    for paragraph in text.split("\n"):
        if not paragraph:
            lines += 1
        else:
            lines += max(1, -(-len(paragraph) // chars_per_line))  # ceil division
    return lines * fontsize * line_spacing


def export_searchable_pdf(
    document: Document,
    output_path: str | Path,
    use_corrected: bool = True,
    show_confidence_heatmap: bool = False,
) -> tuple[Path, list[str]]:
    """Export a searchable PDF with the original scan as background.

    The text layer uses PDF's invisible text rendering (render mode 3)
    so it's selectable/searchable but doesn't visually cover the image.

    Args:
        document: The processed Document model.
        output_path: Where to write the output PDF.
        use_corrected: Use corrected_text when available (True) or original OCR (False).
        show_confidence_heatmap: Overlay a semi-transparent heatmap (debug mode).

    Returns:
        Tuple of (path to generated PDF, list of warning messages).
    """
    import fitz  # PyMuPDF

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_doc = fitz.open()  # new empty PDF
    all_warnings: list[str] = []

    for page in document.pages:
        # Determine page size from the source image
        if page.image_path and Path(page.image_path).exists():
            img = Image.open(page.image_path)
            page_w, page_h = img.size
        else:
            page_w, page_h = int(page.width), int(page.height)

        # Convert image pixels (rendered at 300 DPI) to PDF points (72 DPI)
        page_w_pt = page_w * 72 / 300
        page_h_pt = page_h * 72 / 300

        pdf_page = out_doc.new_page(width=page_w_pt, height=page_h_pt)

        # Layer 1: insert the original scan image
        if page.image_path and Path(page.image_path).exists():
            img_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            pdf_page.insert_image(img_rect, filename=page.image_path)

        # Layer 2: overlay confidence heatmap (debug mode, optional)
        if show_confidence_heatmap:
            _add_confidence_heatmap(pdf_page, page, page_w, page_h, page_w_pt, page_h_pt)

        # Layer 3: invisible text layer for searchable/selectable text
        warnings = _add_text_layer(pdf_page, page, page_w, page_h, page_w_pt, page_h_pt, use_corrected)
        all_warnings.extend(warnings)

    out_doc.save(str(output_path), garbage=4, deflate=True)
    out_doc.close()

    return output_path, all_warnings


def _add_text_layer(
    pdf_page,
    page: Page,
    img_w: float,
    img_h: float,
    pt_w: float,
    pt_h: float,
    use_corrected: bool,
) -> list[str]:
    """Add invisible text overlay — word-level or block-level.

    - Blocks with replacement_text: reflow the new text within the block bbox.
    - Blocks marked deleted: skipped entirely.
    - Normal blocks: place each word at its baseline position using insert_text.

    Returns a list of warning messages (empty if everything fit).
    """
    import fitz

    scale_x = pt_w / img_w
    scale_y = pt_h / img_h
    warnings: list[str] = []

    for block in page.blocks:
        if block.deleted:
            continue

        # --- Block-level replacement: invisible searchable text ---
        if block.replacement_text is not None:
            rect = fitz.Rect(
                block.bbox.x0 * scale_x,
                block.bbox.y0 * scale_y,
                block.bbox.x1 * scale_x,
                block.bbox.y1 * scale_y,
            )
            original_heights = [
                word.bbox.height * scale_y
                for line in block.lines
                for word in line.words
                if word.bbox.height > 0
            ]
            fontsize = sorted(original_heights)[len(original_heights) // 2] * 0.9 if original_heights else 9.0
            fontsize = min(14.0, max(6.0, fontsize))

            # Reduce the font only when necessary. Unlike insert_textbox(),
            # insert_text() cannot silently discard a line because of a tight bbox.
            while True:
                replacement_lines = _wrap_text_measured(
                    block.replacement_text, rect.width, fontsize
                )
                line_height = fontsize * 1.2
                if len(replacement_lines) * line_height <= rect.height or fontsize <= 4.0:
                    break
                fontsize = max(4.0, fontsize - 0.5)

            if len(replacement_lines) * line_height > rect.height:
                warnings.append(
                    f"Page {page.number}, block replacement: searchable text exceeds "
                    f"its region ({len(replacement_lines) * line_height:.0f}pt > {rect.height:.0f}pt)"
                )

            for line_index, replacement_line in enumerate(replacement_lines):
                if not replacement_line:
                    continue
                baseline = rect.y0 + fontsize + line_index * line_height
                pdf_page.insert_text(
                    fitz.Point(rect.x0, baseline),
                    replacement_line,
                    fontsize=fontsize,
                    fontname="helv",
                    color=(0, 0, 0),
                    render_mode=3,
                )
            continue

        # --- Word-level: place each word at its baseline position ---
        # Using insert_text() instead of insert_textbox() avoids silent clipping
        # when the word's bbox is too narrow for the rendered text.
        for line in block.lines:
            for word in line.words:
                text = word.corrected_text if (use_corrected and word.corrected_text) else word.text
                if not text.strip():
                    continue

                # Baseline position: bottom-left of the word's bounding box
                x_pt = word.bbox.x0 * scale_x
                y_pt = word.bbox.y1 * scale_y
                fontsize = (word.bbox.y1 - word.bbox.y0) * scale_y * 0.9

                pdf_page.insert_text(
                    fitz.Point(x_pt, y_pt),
                    text,
                    fontsize=fontsize,
                    fontname="helv",
                    color=(0, 0, 0),
                    render_mode=3,  # invisible
                )

    return warnings


def _add_confidence_heatmap(
    pdf_page,
    page: Page,
    img_w: float,
    img_h: float,
    pt_w: float,
    pt_h: float,
) -> None:
    """Overlay semi-transparent rectangles showing OCR confidence.

    Green = high confidence (> 0.8)
    Yellow = medium confidence (0.6-0.8)
    Red = low confidence (< 0.6)
    """
    import fitz

    scale_x = pt_w / img_w
    scale_y = pt_h / img_h

    for block in page.blocks:
        if block.deleted or block.replacement_text is not None:
            continue

        for line in block.lines:
            for word in line.words:
                conf = word.confidence
                if conf >= 0.8:
                    color = (0, 1, 0)       # green
                elif conf >= 0.6:
                    color = (1, 1, 0)       # yellow
                else:
                    color = (1, 0, 0)       # red

                rect = fitz.Rect(
                    word.bbox.x0 * scale_x,
                    word.bbox.y0 * scale_y,
                    word.bbox.x1 * scale_x,
                    word.bbox.y1 * scale_y,
                )

                # Semi-transparent fill
                pdf_page.draw_rect(rect, color=color, fill=color, fill_opacity=0.25)


def export_overlay_preview(
    document: Document,
    output_path: str | Path,
    page_numbers: list[int] | None = None,
) -> tuple[Path, list[str]]:
    """Export a visual preview: original image + visible text overlay.

    Unlike the searchable PDF, here the text is VISIBLE — colored by confidence.
    Useful for manual review before final export.

    Args:
        document: The Document model.
        output_path: Where to write the preview PDF.
        page_numbers: Which pages to include (None = all).

    Returns:
        Tuple of (path to preview PDF, list of warning messages).
    """
    import fitz

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    out_doc = fitz.open()
    all_warnings: list[str] = []

    for page in document.pages:
        if page_numbers and page.number not in page_numbers:
            continue

        if page.image_path and Path(page.image_path).exists():
            img = Image.open(page.image_path)
            img_w, img_h = img.size
        else:
            img_w, img_h = int(page.width), int(page.height)

        page_w_pt = img_w * 72 / 300
        page_h_pt = img_h * 72 / 300
        scale_x = page_w_pt / img_w
        scale_y = page_h_pt / img_h

        pdf_page = out_doc.new_page(width=page_w_pt, height=page_h_pt)

        # Background image (slightly faded)
        if page.image_path and Path(page.image_path).exists():
            img_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            pdf_page.insert_image(img_rect, filename=page.image_path)

        # Visible text overlay — colored by confidence
        for block in page.blocks:
            if block.deleted:
                continue

            # Block-level replacement: show in blue with targeted white-out
            if block.replacement_text is not None:
                rect = fitz.Rect(
                    block.bbox.x0 * scale_x,
                    block.bbox.y0 * scale_y,
                    block.bbox.x1 * scale_x,
                    block.bbox.y1 * scale_y,
                )

                text_lines = block.replacement_text.count("\n") + 1
                fontsize = min(rect.height / (text_lines * 1.35), 14)
                fontsize = max(fontsize, 6)

                # White-out only the rows the replacement text actually needs
                needed_height = _estimate_text_height(
                    block.replacement_text, rect.width, fontsize
                )
                needed_height = min(needed_height, rect.height)

                white_rect = fitz.Rect(
                    rect.x0, rect.y0,
                    rect.x1, rect.y0 + needed_height,
                )
                pdf_page.draw_rect(white_rect, color=(1, 1, 1), fill=(1, 1, 1), fill_opacity=0.95)

                # Draw a subtle blue outline around the white-out area
                pdf_page.draw_rect(white_rect, color=(0, 0.4, 0.8), fill=None, width=1.5)
                pdf_page.insert_textbox(
                    rect,
                    block.replacement_text,
                    fontsize=fontsize,
                    fontname="helv",
                    color=(0, 0.2, 0.6),  # blue text for replacements
                    render_mode=0,
                    align=0,
                )
                continue

            # Word-level: colored by confidence, placed at baseline
            for line in block.lines:
                for word in line.words:
                    text = word.display_text
                    if not text.strip():
                        continue

                    conf = word.confidence
                    if conf >= 0.8:
                        color = (0, 0.4, 0)          # dark green
                    elif conf >= 0.6:
                        color = (0.8, 0.6, 0)        # amber
                    else:
                        color = (0.8, 0, 0)          # red

                    x_pt = word.bbox.x0 * scale_x
                    y_pt = word.bbox.y1 * scale_y
                    fontsize = (word.bbox.y1 - word.bbox.y0) * scale_y * 0.9

                    pdf_page.insert_text(
                        fitz.Point(x_pt, y_pt),
                        text,
                        fontsize=fontsize,
                        fontname="helv",
                        color=color,
                        render_mode=0,              # visible
                    )

    out_doc.save(str(output_path), garbage=4, deflate=True)
    out_doc.close()

    return output_path, all_warnings


def apply_corrections(
    document: Document,
    corrections: dict[str, str],
    match_mode: str = "exact",
) -> Document:
    """Apply a dictionary of corrections to the document.

    Args:
        document: The Document model.
        corrections: Dict mapping original_text -> corrected_text.
        match_mode:
            - "exact": match the full word exactly
            - "contains": match if original_text is a substring

    Returns:
        The same document (mutated in place).
    """
    for page in document.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    for orig, corrected in corrections.items():
                        if match_mode == "exact" and word.text == orig:
                            word.corrected_text = corrected
                            word.status = CorrectionStatus.CORRECTED
                        elif match_mode == "contains" and orig in word.text:
                            word.corrected_text = word.text.replace(orig, corrected)
                            word.status = CorrectionStatus.CORRECTED

    return document
