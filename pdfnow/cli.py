"""Command-line interface for PdfNow.

Three-step workflow:
  1. pdfnow ocr input.pdf         → extracts text with coordinates
  2. pdfnow edit project.json     → edit the JSON (or use corrections file)
  3. pdfnow export project.json   → generate searchable output PDF
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress

from .model import Document, CorrectionStatus
from .ocr import run_ocr_on_pdf
from .export import export_searchable_pdf, export_overlay_preview, apply_corrections
from .style import extract_style, extract_structured_text, analyze_layout, wrap_text_to_lines

console = Console()


@click.group()
@click.version_option()
def main():
    """PdfNow — Edit scanned PDFs while preserving visual style."""
    pass


@main.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("-l", "--lang", default="ita", help="OCR language: ita, eng, fra, deu, ...")
@click.option("--no-preprocess", is_flag=True, help="Skip image pre-processing")
@click.option("-o", "--output", default=None, help="Output project JSON path")
@click.option("-p", "--max-pages", type=int, default=None, help="Process only first N pages")
def ocr(pdf_path: str, lang: str, no_preprocess: bool, output: str | None, max_pages: int | None):
    """Step 1: Run OCR on a scanned PDF and save the project.

    Extracts text with coordinates and confidence scores.
    Saves the document model as a JSON project file.

    Examples:
        pdfnow ocr scanned.pdf
        pdfnow ocr scanned.pdf -l eng -o my_project.json
    """
    pdf_path = Path(pdf_path).resolve()

    if output is None:
        output = Path("export") / pdf_path.with_suffix(".pdfnow.json").name
    output_path = Path(output)

    console.print(Panel.fit(
        f"[bold]PdfNow OCR[/bold]\n"
        f"Source: {pdf_path}\n"
        f"Language: {lang}\n"
        f"Preprocess: {'yes' if not no_preprocess else 'no'}\n"
        f"Output: {output_path}",
        title="Step 1 — OCR"
    ))

    with Progress() as progress:
        task = progress.add_task("[cyan]Processing...", total=None)

        document = run_ocr_on_pdf(
            pdf_path,
            preprocess=not no_preprocess,
            lang=lang,
            max_pages=max_pages,
        )

        progress.update(task, completed=100)

    # Save project
    document.save(output_path)

    # Report
    _print_document_report(document)
    console.print(f"\n[green]✓[/green] Project saved to: [bold]{output_path}[/bold]")
    console.print(f"[dim]Next: edit corrections in the JSON, then run 'pdfnow export {output_path}'[/dim]")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("-c", "--corrections", default=None, help="Path to corrections JSON file")
@click.option("--edit-word", nargs=3, multiple=True,
              help="Correct a word: PAGE WORD_INDEX NEW_TEXT (can repeat)")
def edit(project_path: str, corrections: str | None, edit_word: tuple):
    """Step 2: Apply corrections to the OCR output.

    Corrections can come from:
    - A JSON file: {"original_word": "corrected_word", ...}
    - CLI flags: --edit-word 1 5 "nuovo testo"

    After editing, save the updated project.
    """
    project_path = Path(project_path).resolve()
    document = Document.load(project_path)

    changes = 0

    # Apply corrections from JSON file
    if corrections:
        corrections_path = Path(corrections)
        if not corrections_path.exists():
            console.print(f"[red]Corrections file not found: {corrections_path}[/red]")
            sys.exit(1)
        corr_data = json.loads(corrections_path.read_text(encoding="utf-8"))
        document = apply_corrections(document, corr_data, match_mode="exact")
        changes += len(corr_data)
        console.print(f"[green]✓[/green] Applied {len(corr_data)} corrections from {corrections_path}")

    # Apply per-word corrections from CLI
    for page_num_str, word_idx_str, new_text in edit_word:
        page_num = int(page_num_str)
        word_idx = int(word_idx_str)

        if page_num < 1 or page_num > len(document.pages):
            console.print(f"[red]Invalid page number: {page_num}[/red]")
            continue

        page = document.pages[page_num - 1]
        flat_words = [
            w for block in page.blocks
            for line in block.lines
            for w in line.words
        ]

        if word_idx < 0 or word_idx >= len(flat_words):
            console.print(f"[red]Invalid word index {word_idx} on page {page_num} (max: {len(flat_words)-1})[/red]")
            continue

        word = flat_words[word_idx]
        old_text = word.text
        word.corrected_text = new_text
        word.status = CorrectionStatus.CORRECTED
        changes += 1
        console.print(f"  Page {page_num}, word #{word_idx}: [red]{old_text}[/red] → [green]{new_text}[/green]")

    # Save
    document.save(project_path)
    console.print(f"\n[green]✓[/green] Project saved with {changes} change(s)")
    console.print(f"[dim]Next: run 'pdfnow export {project_path}' to generate the PDF[/dim]")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("-o", "--output", default=None, help="Output PDF path")
@click.option("--preview", is_flag=True, help="Generate a visual preview with colored text overlay")
@click.option("--heatmap", is_flag=True, help="Include confidence heatmap in the searchable PDF")
@click.option("--original-text", is_flag=True, help="Use original OCR text (skip corrections)")
def export(project_path: str, output: str | None, preview: bool, heatmap: bool, original_text: bool):
    """Step 3: Export the final PDF.

    Generates a searchable PDF with:
    - Original scan as background (visual style preserved)
    - Invisible text layer for searching/selecting
    - Corrections applied (unless --original-text)

    Use --preview for a visible-text review version.
    """
    project_path = Path(project_path).resolve()
    document = Document.load(project_path)

    if output is None:
        suffix = "_preview.pdf" if preview else "_searchable.pdf"
        output = Path("export") / project_path.with_suffix(suffix).name
    output_path = Path(output)

    console.print(Panel.fit(
        f"[bold]Export PDF[/bold]\n"
        f"Project: {project_path}\n"
        f"Output: {output_path}\n"
        f"Mode: {'preview' if preview else 'searchable'}\n"
        f"Use corrections: {'no' if original_text else 'yes'}",
        title="Step 3 — Export"
    ))

    warnings: list[str] = []

    if preview:
        _, warnings = export_overlay_preview(document, output_path)
        console.print("[green]✓[/green] Preview PDF generated with visible text overlay")
        console.print("  [dim]Green text = high confidence, Red = low confidence[/dim]")
    else:
        _, warnings = export_searchable_pdf(
            document,
            output_path,
            use_corrected=not original_text,
            show_confidence_heatmap=heatmap,
        )
        console.print("[green]✓[/green] Searchable PDF generated")
        console.print("  [dim]Text is invisible but selectable/searchable[/dim]")
        console.print("  [dim]The visual appearance matches the original scan[/dim]")

    if warnings:
        console.print("\n[yellow]⚠ Warnings:[/yellow]")
        for w in warnings:
            console.print(f"  [yellow]• {w}[/yellow]")

    console.print(f"\n[bold]Output:[/bold] {output_path}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
def info(project_path: str):
    """Show information about a PdfNow project."""
    document = Document.load(project_path)
    _print_document_report(document)

    # Show pages with text
    for page in document.pages:
        if not page.blocks:
            continue
        console.print(f"\n[bold]── Page {page.number} ──[/bold]")
        for block in page.blocks:
            text_preview = block.text[:120] + "..." if len(block.text) > 120 else block.text
            conf_color = "green" if block.avg_confidence >= 0.8 else "yellow" if block.avg_confidence >= 0.6 else "red"
            console.print(f"  [{conf_color}]{block.avg_confidence:.0%}[/{conf_color}] {text_preview}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
def blocks(project_path: str):
    """List all blocks with indices for block-level editing.

    Each block gets a unique index like '1:3' (page 1, block 3 on that page).
    Use these indices with 'pdfnow block-edit'.
    """
    document = Document.load(project_path)

    for page in document.pages:
        console.print(f"\n[bold]── Page {page.number} ──[/bold]")
        for i, block in enumerate(page.blocks):
            status = ""
            if block.deleted:
                status = " [red]DELETED[/red]"
            elif block.replacement_text is not None:
                status = " [blue]REPLACED[/blue]"
            text_preview = block.text[:100].replace("\n", " ") + ("..." if len(block.text) > 100 else "")
            conf_color = "green" if block.avg_confidence >= 0.8 else "yellow" if block.avg_confidence >= 0.6 else "red"
            console.print(
                f"  [{conf_color}]{page.number}:{i}[/{conf_color}]{status} "
                f"([{conf_color}]{block.avg_confidence:.0%}[/{conf_color}]) "
                f"{text_preview}"
            )


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("-b", "--block-id", multiple=True, help="Block index as 'page:idx' to target")
@click.option("--replace", multiple=True, help="Replacement text for block (paired with -b)")
@click.option("--delete", multiple=True, help="Block index to delete (page:idx)")
@click.option("-f", "--file", default=None, help="JSON file with block edits")
def block_edit(
    project_path: str,
    block_id: tuple,
    replace: tuple,
    delete: tuple,
    file: str | None,
):
    """Edit blocks structurally: replace text or delete blocks.

    Examples:
        pdfnow block-edit project.json -b 1:2 --replace "Nuovo testo"
        pdfnow block-edit project.json --delete 1:5 --delete 1:7
        pdfnow block-edit project.json -f block_edits.json

    JSON format:
        {"edits": [
            {"page": 1, "block": 2, "replacement_text": "Nuovo testo"},
            {"page": 1, "block": 5, "delete": true}
        ]}
    """
    document = Document.load(project_path)
    changes = 0

    # --- Apply from JSON file ---
    if file:
        file_path = Path(file)
        if not file_path.exists():
            console.print(f"[red]File not found: {file}[/red]")
            sys.exit(1)
        data = json.loads(file_path.read_text(encoding="utf-8"))
        for edit in data.get("edits", []):
            page_num = edit["page"]
            block_idx = edit["block"]
            if page_num < 1 or page_num > len(document.pages):
                console.print(f"[red]Invalid page: {page_num}[/red]")
                continue
            page = document.pages[page_num - 1]
            if block_idx < 0 or block_idx >= len(page.blocks):
                console.print(f"[red]Invalid block index: {page_num}:{block_idx}[/red]")
                continue
            block = page.blocks[block_idx]
            if edit.get("delete"):
                block.deleted = True
                console.print(f"  [red]✕[/red] Deleted block {page_num}:{block_idx}")
                changes += 1
            elif "replacement_text" in edit:
                block.replacement_text = edit["replacement_text"]
                console.print(f"  [blue]↻[/blue] Replaced block {page_num}:{block_idx}")
                changes += 1

    # --- Apply from CLI flags ---
    # Deletions
    for del_id in delete:
        parts = del_id.split(":")
        if len(parts) != 2:
            console.print(f"[red]Invalid block id: {del_id} (use page:idx)[/red]")
            continue
        page_num, block_idx = int(parts[0]), int(parts[1])
        if page_num < 1 or page_num > len(document.pages):
            console.print(f"[red]Invalid page: {page_num}[/red]")
            continue
        page = document.pages[page_num - 1]
        if block_idx < 0 or block_idx >= len(page.blocks):
            console.print(f"[red]Invalid block index: {page_num}:{block_idx}[/red]")
            continue
        page.blocks[block_idx].deleted = True
        console.print(f"  [red]✕[/red] Deleted block {page_num}:{block_idx}")
        changes += 1

    # Replacements
    if len(block_id) != len(replace):
        console.print("[red]--replace and -b must be paired 1:1[/red]")
        if block_id:
            sys.exit(1)
    else:
        for bid, rtext in zip(block_id, replace):
            parts = bid.split(":")
            if len(parts) != 2:
                console.print(f"[red]Invalid block id: {bid}[/red]")
                continue
            page_num, block_idx = int(parts[0]), int(parts[1])
            if page_num < 1 or page_num > len(document.pages):
                console.print(f"[red]Invalid page: {page_num}[/red]")
                continue
            page = document.pages[page_num - 1]
            if block_idx < 0 or block_idx >= len(page.blocks):
                console.print(f"[red]Invalid block index: {page_num}:{block_idx}[/red]")
                continue
            page.blocks[block_idx].replacement_text = rtext
            console.print(f"  [blue]↻[/blue] Replaced block {page_num}:{block_idx}")
            changes += 1

    document.save(project_path)
    console.print(f"\n[green]✓[/green] Project saved with {changes} block edit(s)")
    console.print(f"[dim]Next: run 'pdfnow export {project_path} --preview' to review[/dim]")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("-p", "--page", type=int, default=1, help="Page number to extract")
@click.option("-o", "--output", default=None, help="Output .txt file path")
def text(project_path: str, page: int, output: str | None):
    """Extract the structured text of a page for editing.

    Preserves line breaks, paragraph spacing, and text flow.
    Edit this file, then rebuild with 'pdfnow rebuild'.
    """
    document = Document.load(project_path)

    if page < 1 or page > len(document.pages):
        console.print(f"[red]Page {page} not found (1-{len(document.pages)})[/red]")
        sys.exit(1)

    page_obj = document.pages[page - 1]
    structured = extract_structured_text(page_obj)

    if output is None:
        src = Path(document.source_path)
        output = Path("export") / f"{src.stem}_p{page}_edit.txt"
    output_path = Path(output)
    output_path.write_text(structured, encoding="utf-8")

    # Also extract and print style info
    style = extract_style(page_obj)

    console.print(Panel.fit(
        f"[bold]Extracted text — Page {page}[/bold]\n"
        f"Lines: {structured.count(chr(10)) + 1}\n"
        f"Chars: {len(structured)}",
        title="Text extraction"
    ))
    console.print(f"[green]✓[/green] Saved to: [bold]{output_path}[/bold]")
    console.print()
    console.print("[bold]Extracted style metrics:[/bold]")
    console.print(f"  Page: {style.page_width_pt:.0f}×{style.page_height_pt:.0f} pt")
    console.print(f"  Margins: L={style.margin_left_pt:.0f} R={style.margin_right_pt:.0f} T={style.margin_top_pt:.0f} B={style.margin_bottom_pt:.0f}")
    console.print(f"  Body font: {style.body_font_size_pt:.1f}pt, spacing: {style.line_spacing:.2f}×")
    console.print(f"  Paragraph gap: {style.paragraph_spacing_pt:.0f}pt")
    console.print(f"  Alignment: {style.text_align}")
    console.print()
    console.print("[dim]Edit the .txt file, then run:[/dim]")
    console.print(f"[dim]  pdfnow rebuild {project_path} -t {output_path}[/dim]")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("-t", "--text-file", required=True, type=click.Path(exists=True),
              help="Edited .txt file with the new content")
@click.option("-p", "--page", type=int, default=1, help="Page number to rebuild")
@click.option("-o", "--output", default=None, help="Output PDF path")
@click.option("--font-size", type=float, default=None, help="Override body font size (pt)")
@click.option("--font-name", type=click.Choice(["tiro", "helv", "cour"]),
              default=None, help="Font: tiro=Times Roman, helv=Helvetica, cour=Courier")
@click.option("--keep-sidebar", is_flag=True, default=False,
              help="Keep sidebar blocks (stamps, registration) from original scan")
@click.option("--align", type=click.Choice(["left", "center", "right", "justify"]),
              default=None, help="Override text alignment")
@click.option("--margin-left", type=float, default=None, help="Override left margin (pt)")
@click.option("--margin-right", type=float, default=None, help="Override right margin (pt)")
@click.option("--margin-top", type=float, default=None, help="Override top margin (pt)")
@click.option("--para-gap", type=float, default=None, help="Override paragraph spacing (pt)")
@click.option("--line-spacing", type=click.FloatRange(min=0.8, max=3.0), default=None,
              help="Override line spacing multiplier")
def rebuild(project_path: str, text_file: str, page: int, output: str | None,
            font_size: float | None, font_name: str | None, keep_sidebar: bool,
            align: str | None,
            margin_left: float | None, margin_right: float | None,
            margin_top: float | None, para_gap: float | None,
            line_spacing: float | None):
    """Rebuild a PDF page from edited text, matching the original style.

    Reads the edited .txt, extracts style from the scanned page,
    and generates a new PDF with the text styled like the original.

    Use --font-size and --align to override auto-detected values.
    """
    import fitz  # PyMuPDF

    document = Document.load(project_path)

    if page < 1 or page > len(document.pages):
        console.print(f"[red]Page {page} not found (1-{len(document.pages)})[/red]")
        sys.exit(1)

    page_obj = document.pages[page - 1]
    edited_text = Path(text_file).read_text(encoding="utf-8")
    # PyMuPDF's Base-14 fonts do not encode every typographic punctuation
    # character consistently. Normalize them before measuring and rendering.
    edited_text = edited_text.translate(str.maketrans({
        "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "-",
        "\u00a0": " ",
    }))
    style = extract_style(page_obj)

    # Apply overrides
    if font_size:
        style.body_font_size_pt = font_size
    if font_name:
        style.font_name = font_name
    if align:
        style.text_align = align
    if margin_left is not None:
        style.margin_left_pt = margin_left
    if margin_right is not None:
        style.margin_right_pt = margin_right
    if margin_top is not None:
        style.margin_top_pt = margin_top
    if para_gap is not None:
        style.paragraph_spacing_pt = para_gap
    if line_spacing is not None:
        style.line_spacing = line_spacing

    if output is None:
        src = Path(document.source_path)
        output = Path("export") / f"{src.stem}_p{page}_rebuilt.pdf"

    console.print(Panel.fit(
        f"[bold]Rebuilding page {page}[/bold]\n"
        f"Font: {style.body_font_size_pt:.1f}pt {style.font_name}\n"
        f"Margins: L={style.margin_left_pt:.0f} R={style.margin_right_pt:.0f} T={style.margin_top_pt:.0f}\n"
        f"Alignment: {style.text_align}",
        title="Style applied"
    ))

    # --- Analyze layout ---
    layout = analyze_layout(page_obj)

    # --- Build PDF ---
    out_doc = fitz.open()
    pdf_page = out_doc.new_page(width=style.page_width_pt, height=style.page_height_pt)
    scale = 72.0 / 300.0  # image px → PDF points

    # --- Background: original scan with main text area whited out ---
    if keep_sidebar and page_obj.image_path and Path(page_obj.image_path).exists():
        from PIL import Image as PILImage, ImageDraw
        import io

        page_img = PILImage.open(page_obj.image_path)

        if layout.main_text_bbox:
            mx0, my0, mx1, my1 = layout.main_text_bbox
            # Tiny padding to ensure clean edges, but don't eat into sidebar
            pad = 5
            x0 = max(0, int(mx0) - pad)
            y0 = max(0, int(my0) - pad)
            x1 = min(page_img.width, int(mx1) + pad)
            y1 = min(page_img.height, int(my1) + pad)

            draw = ImageDraw.Draw(page_img)
            draw.rectangle([x0, y0, x1, y1], fill="white")
            console.print(f"  [dim]Cleaned text area: ({x0},{y0})-({x1},{y1}) out of {page_img.size}[/dim]")

        # Save cleaned image bytes for potential retries
        buf = io.BytesIO()
        page_img.save(buf, format="PNG")
        bg_image_bytes = buf.getvalue()  # keep a copy

        img_rect = fitz.Rect(0, 0, style.page_width_pt, style.page_height_pt)
        pdf_page.insert_image(img_rect, stream=bg_image_bytes)
        console.print("  [dim]Background: original scan (text area cleaned)[/dim]")
        has_background = True
    else:
        has_background = False
        if keep_sidebar:
            console.print("  [yellow]No page image found — skipping background[/yellow]")

    # --- Determine text rendering area ---
    if layout.main_text_bbox:
        mx0, my0, mx1, my1 = layout.main_text_bbox
        l_margin = mx0 * scale
        r_margin = style.page_width_pt - (mx1 * scale)
        t_margin = my0 * scale
        b_margin = style.page_height_pt - (my1 * scale)
    else:
        l_margin = style.margin_left_pt
        r_margin = style.margin_right_pt
        t_margin = style.margin_top_pt
        b_margin = style.margin_bottom_pt

    text_rect = fitz.Rect(
        l_margin,
        t_margin,
        style.page_width_pt - r_margin,
        style.page_height_pt - b_margin,
    )

    console.print(
        f"  [dim]Text area: x={l_margin:.0f}-{style.page_width_pt - r_margin:.0f}, "
        f"y={t_margin:.0f}-{style.page_height_pt - b_margin:.0f}[/dim]"
    )

    # --- Render the edited text line by line with real line_spacing ---
    paragraphs = [p.strip() for p in edited_text.split("\n\n") if p.strip()]
    fontsize = style.body_font_size_pt
    line_height = fontsize * style.line_spacing

    # --- Paragraph-level styling ---
    # Keep headings and role labels distinct instead of making whole sections bold.
    CENTERED_BOLD_PATTERNS = [
        "COMPRAVENDITA",
        "REPUBBLICA ITALIANA",
        "SONO PRESENTI:",
        "Art. 1) CONSENSO E OGGETTO",
        "Art. 2)", "Art. 3)", "Art. 4)", "Art. 5)",
    ]
    CENTERED_ITALIC_PATTERNS = [
        "quale parte venditrice",
        "quale parte acquirente",
    ]
    ITALIC_PATTERNS = ["il tutto censito"]

    def starts_with_any(para: str, patterns: list[str]) -> bool:
        text = para.replace("\n", " ").strip()
        return any(text == pattern or text.startswith(pattern) for pattern in patterns)

    def is_bold_heading(para: str) -> bool:
        text = para.replace("\n", " ").strip()
        return (
            starts_with_any(para, CENTERED_BOLD_PATTERNS)
            or bool(re.match(r"^Art\.\s*\d+\)", text, flags=re.IGNORECASE))
            or (text.isupper() and len(text) <= 80)
        )

    y = text_rect.y0
    align_map = {"left": 0, "center": 1, "right": 2, "justify": 3}
    body_align = align_map.get(style.text_align, 0)

    rendered_paragraphs = 0
    rebuild_warnings: list[str] = []
    total_lines_rendered = 0

    for i, para in enumerate(paragraphs):
        bold = is_bold_heading(para)
        centered_italic = starts_with_any(para, CENTERED_ITALIC_PATTERNS)
        italic = centered_italic or starts_with_any(para, ITALIC_PATTERNS)

        if bold:
            p_fontsize = fontsize * 1.2
            bold_map = {"tiro": "tibo", "helv": "hebo", "cour": "cobo"}
            p_fontname = bold_map.get(style.font_name, style.font_name)
            p_align = 1
            p_line_height = p_fontsize * style.line_spacing
        elif italic:
            italic_map = {"tiro": "tiit", "helv": "heit", "cour": "coit"}
            p_fontsize = fontsize
            p_fontname = italic_map.get(style.font_name, style.font_name)
            p_align = 1 if centered_italic else body_align
            p_line_height = line_height
        else:
            p_fontsize = fontsize
            p_fontname = style.font_name
            p_align = body_align
            p_line_height = line_height

        # Wrap paragraph text into lines that fit the text area width
        max_width = text_rect.width
        para_lines = wrap_text_to_lines(para, max_width, p_fontsize, p_fontname)

        if not para_lines:
            y += style.paragraph_spacing_pt
            rendered_paragraphs += 1
            continue

        # Check if the whole paragraph fits on the remaining page
        para_total_height = len(para_lines) * p_line_height + style.paragraph_spacing_pt
        if y + para_total_height > text_rect.y1:
            rebuild_warnings.append(
                f"Page full before paragraph {i+1} of {len(paragraphs)} "
                f"({len(paragraphs) - i} paragraphs omitted)"
            )
            break

        # Render each line at exact baseline positions
        for j, line_text in enumerate(para_lines):
            line_y = y + (j + 1) * p_line_height  # baseline

            # Center-align: compute x offset approximately
            if p_align == 1:
                text_width_est = fitz.get_text_length(
                    line_text, fontname=p_fontname, fontsize=p_fontsize
                )
                x_offset = (text_rect.width - text_width_est) / 2
                x_pos = text_rect.x0 + max(0, x_offset)
            else:
                x_pos = text_rect.x0

            pdf_page.insert_text(
                fitz.Point(x_pos, line_y),
                line_text,
                fontsize=p_fontsize,
                fontname=p_fontname,
                color=(0, 0, 0),
                render_mode=0,
            )
            total_lines_rendered += 1

        y += len(para_lines) * p_line_height
        y += style.paragraph_spacing_pt * (0.3 if bold else 0.5)
        rendered_paragraphs += 1

    if rebuild_warnings:
        out_doc.close()
        raise click.ClickException(
            "Rebuild aborted to avoid a partial PDF: " + "; ".join(rebuild_warnings)
        )

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_doc.save(str(output_path), garbage=4, deflate=True)
    out_doc.close()

    console.print(f"\n[green]✓[/green] Rebuilt PDF: [bold]{output}[/bold]")
    console.print(f"  [dim]Font: {fontsize:.1f}pt, spacing: {style.line_spacing:.2f}×, "
                 f"paragraphs: {rendered_paragraphs}/{len(paragraphs)}, "
                 f"lines: {total_lines_rendered}[/dim]")

def _print_document_report(document: Document):
    """Print a summary table for the document."""
    table = Table(title="Document Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Source", str(Path(document.source_path).name))
    table.add_row("Pages", str(len(document.pages)))
    table.add_row("Total words", str(document.total_words))
    table.add_row("Low-confidence words", f"{document.low_confidence_words} ([red]{document.low_confidence_words}[/red])")
    table.add_row("Overall confidence", f"{document.overall_confidence:.1%}")

    if document.metadata:
        for k, v in document.metadata.items():
            if k not in ("page_count",):
                table.add_row(f"  {k}", str(v))

    console.print(table)


if __name__ == "__main__":
    main()
