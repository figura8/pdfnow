"""
Reflow pages 1-7 as a continuous stream with uniform style,
rasterize for visual consistency, re-add searchable layer,
and append attachments (pages 11-13).

Core principle: When text changes affect pagination, rebuild the
entire textual section as a single flow — not page by page.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFilter


# ═══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

PROJECT_PATH = Path("export/atto_13p.json")
REFERENCE_PDF_PATH = Path(r"C:\Users\maurizio\Downloads\REP 1182.PDF.pdf")
EDITED_P1_PATH = Path("pagina1_v2.txt")
# Edited .txt files for pages that had Mariano/Giovanna modifications
EDITED_TEXTS = {
    1: Path("pagina1_v2.txt"),
    3: Path("export/pagina3_ocr.txt"),
    5: Path("export/pagina5_ocr.txt"),
    7: Path("export/pagina7_ocr.txt"),
}
OUTPUT_PATH = Path("export/atto_reference_francesco_v5.pdf")
REFERENCE_ATTACHMENT_PAGES = (12, 13)

# Global style (single style for all 7 textual pages)
BODY_FONT = "tiro"          # Times Roman
BODY_SIZE = 11.7            # pt — maximum stable size with validated pagination
LINE_SPACING = 1.35         # multiplier on fontsize
PARA_SPACING = 2.0          # pt after paragraphs
BALANCE_RESERVE_PT = 180.0  # reserve on pages 1-6: target 15-20 lines on page 7
TITLE_SCALE = 1.15          # title size relative to body
TITLE_FONT = "tibo"         # Times Bold
ITALIC_FONT = "tiit"        # Times Italic

# Text area in pixels at 300 DPI (body column only)
SCALE = 72.0 / 300.0
TEXT_LEFT_PX = 320
TEXT_RIGHT_PX = 1866
TEXT_TOP_PX = 384
TEXT_BOTTOM_PX = 3403

# Rasterization
RASTER_DPI = 300
BLUR_RADIUS = 0.25
JPEG_QUALITY = 92

# Character normalization map
CHAR_MAP = {
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
    "\u00a0": " ",
    "\u00b7": "-",   # middle dot
    "\u2012": "-",   # figure dash
    "\u2026": "...", # horizontal ellipsis
    "\u20ac": "EUR", # euro sign
    "\u00a3": "GBP", # pound sign
    "\u00a9": "(c)", # copyright
    "\u00bb": ">>",  # right guillemet
    "\ufb00": "ff",  # ff ligature
    "\ufb01": "fi",  # fi ligature
    "\ufb02": "fl",  # fl ligature
    "\ufb03": "ffi", # ffi ligature
    "\ufb04": "ffl", # ffl ligature
}


# ═══════════════════════════════════════════════════════════════════════════
# 2. LOAD AND CLASSIFY
# ═══════════════════════════════════════════════════════════════════════════

def load_project(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def classify_page(page: dict) -> None:
    """Label blocks as body/sidebar/header/footer if not already labeled."""
    pw = page["width"]
    sidebar_x = pw * 0.70
    header_y = 450
    footer_y = page["height"] * 0.94

    for block in page["blocks"]:
        if block.get("label"):
            continue
        if block["bbox"]["x0"] > sidebar_x:
            block["label"] = "sidebar"
        elif block["bbox"]["y1"] < header_y and block["bbox"]["x1"] < sidebar_x:
            block["label"] = "header"
        elif block["bbox"]["y0"] > footer_y:
            block["label"] = "footer"
        else:
            block["label"] = "body"


# ═══════════════════════════════════════════════════════════════════════════
# 3. BUILD TEXT FLOW
# ═══════════════════════════════════════════════════════════════════════════

def _line_bbox(line: dict) -> dict:
    """Compute line bbox from its words (bbox is not serialized in JSON)."""
    words = line.get("words", [])
    if not words:
        return {"x0": 0, "y0": 0, "x1": 0, "y1": 0}
    return {
        "x0": min(w["bbox"]["x0"] for w in words),
        "y0": min(w["bbox"]["y0"] for w in words),
        "x1": max(w["bbox"]["x1"] for w in words),
        "y1": max(w["bbox"]["y1"] for w in words),
    }


def extract_body_text(page: dict) -> str:
    """Extract body text from a page, sorted by reading order."""
    classify_page(page)

    lines: list[tuple[float, float, str]] = []  # (y0, x0, text)
    for block in page["blocks"]:
        if block.get("label") not in ("body", ""):
            continue
        if block.get("deleted"):
            continue
        for line in block.get("lines", []):
            words = [w["text"] for w in line.get("words", [])]
            if words:
                bbox = _line_bbox(line)
                lines.append((bbox["y0"], bbox["x0"], " ".join(words)))

    lines.sort(key=lambda x: (x[0], x[1]))
    return "\n".join(text for _, _, text in lines)


def dehyphenate(text: str) -> str:
    """Merge only clear OCR word breaks, never across blank paragraphs."""
    return re.sub(r"(?<=\w)-\n(?=[a-zà-öø-ÿ])", "", text)


def merge_continuation_lines(text: str) -> str:
    """Convert internal line breaks to spaces, preserving blank-line paragraphs."""
    paragraphs = text.split("\n\n")
    merged = []
    for para in paragraphs:
        lines = para.split("\n")
        merged.append(" ".join(line.strip() for line in lines if line.strip()))
    return "\n\n".join(merged)


def normalize_text(text: str) -> str:
    """Remove characters that PDF Base-14 fonts render incorrectly."""
    # Build translation table using ordinals (more portable)
    trans = {ord(k): v for k, v in CHAR_MAP.items()}
    return text.translate(trans)


def build_flow(project: dict, edited_texts: dict[int, Path]) -> str:
    """Build the continuous text flow: edited pages + OCR pages 2-7.
    
    Uses edited .txt files for pages that were modified (1,3,5,7),
    and OCR body text for unmodified pages (2,4,6).
    """
    parts: list[str] = []

    for page in project["pages"]:
        pn = page["number"]
        if pn < 1 or pn > 7:
            continue
        
        if pn in edited_texts:
            text = edited_texts[pn].read_text(encoding="utf-8").strip()
            # Edited texts still have OCR line breaks — dehyphenate too
            text = dehyphenate(text)
            text = merge_continuation_lines(text)
        else:
            text = extract_body_text(page)
            text = dehyphenate(text)
            text = merge_continuation_lines(text)
        
        if text:
            parts.append(text)

    full_flow = "\n\n".join(parts)
    full_flow = normalize_text(full_flow)

    # Remove excessive blank lines (more than 2 consecutive newlines)
    while "\n\n\n" in full_flow:
        full_flow = full_flow.replace("\n\n\n", "\n\n")

    return full_flow.strip()


# ═══════════════════════════════════════════════════════════════════════════
# 4. PARAGRAPH DETECTION AND STYLING
# ═══════════════════════════════════════════════════════════════════════════

# Patterns for section headers / titles
ART_PATTERNS = [f"Art.{i})" for i in range(1, 20)] + \
               [f"Art. {i})" for i in range(1, 20)]

ALL_CAPS_TITLES = [
    "COMPRAVENDITA", "REPUBBLICA ITALIANA", "SONO PRESENTI:",
    "PROVENIENZA:", "GARANZIE:", "ANTIRICICLAGGIO:",
]

ITALIC_PATTERNS = [
    "quale parte venditrice",
    "quale parte acquirente",
    "il tutto censito",
]

CENTERED_BOLD_PATTERNS = ART_PATTERNS + ALL_CAPS_TITLES
CENTERED_ITALIC_PATTERNS = ITALIC_PATTERNS[:2]  # venditrice, acquirente

# Headings which OCR / line merging commonly joins to the first sentence.
# Keep these exact: a broad ALL-CAPS regex risks splitting names and legal text.
INLINE_HEADINGS = [
    "quale parte venditrice",
    "quale parte acquirente",
    "PROVENIENZA:",
    "GARANZIE:",
    "PRIVACY:",
    "ANTIRICICLAGGIO:",
    "Art.7) REGIME PATRIMONIALE",
    "Art. 7) REGIME PATRIMONIALE",
    "Art.8) Art.26 del D.P.R. 131/1986",
    "Art. 8) Art.26 del D.P.R. 131/1986",
    "Art.9) ATTESTATO DI PRESTAZIONE ENERGETICA",
    "Art. 9) ATTESTATO DI PRESTAZIONE ENERGETICA",
    "Art.10) PRIVACY E ANTIRICICLAGGIO",
    "Art. 10) PRIVACY E ANTIRICICLAGGIO",
]


def is_all_caps_line(line: str) -> bool:
    """Check if a line is short and ALL CAPS (potential title)."""
    stripped = line.strip()
    if len(stripped) < 5 or len(stripped) > 60:
        return False
    alpha = [c for c in stripped if c.isalpha()]
    if not alpha:
        return False
    return all(c.isupper() for c in alpha)


def classify_paragraph(para: str) -> dict:
    """Return paragraph style info."""
    text = para.strip()
    first_line = text.split("\n")[0].strip()

    # Check centered bold patterns
    for pat in CENTERED_BOLD_PATTERNS:
        if first_line == pat or first_line.startswith(pat):
            return {"font": TITLE_FONT, "size_scale": TITLE_SCALE,
                    "align": "center", "keep_with_next": True}

    # Check all-caps short lines
    if is_all_caps_line(first_line):
        return {"font": TITLE_FONT, "size_scale": TITLE_SCALE,
                "align": "center", "keep_with_next": True}

    # Check centered italic patterns
    for pat in CENTERED_ITALIC_PATTERNS:
        if first_line == pat or first_line.startswith(pat):
            return {"font": ITALIC_FONT, "size_scale": 1.0,
                    "align": "center", "keep_with_next": False}

    # Check italic patterns (e.g., "il tutto censito")
    for pat in ITALIC_PATTERNS:
        if first_line.startswith(pat):
            return {"font": ITALIC_FONT, "size_scale": 1.0,
                    "align": "left", "keep_with_next": False}

    # Default body
    return {"font": BODY_FONT, "size_scale": 1.0,
            "align": "left", "keep_with_next": False}


def split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs, recognizing titles mixed into body blocks."""
    raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]

    result = []
    for para in raw_paras:
        # merge_continuation_lines() intentionally turns wrapped OCR lines into
        # one paragraph. Split known inline headings back out before styling,
        # otherwise the heading style is incorrectly applied to all body text.
        inline_split = False
        for heading in sorted(INLINE_HEADINGS, key=len, reverse=True):
            if para.startswith(heading) and len(para) > len(heading):
                rest = para[len(heading):].strip()
                if rest:
                    result.extend((heading, rest))
                    inline_split = True
                    break
        if inline_split:
            continue

        lines = para.split("\n")
        # If first line is a title pattern, split it off
        first = lines[0].strip()
        is_title = (
            any(first == pat or first.startswith(pat)
                for pat in CENTERED_BOLD_PATTERNS) or
            is_all_caps_line(first) or
            any(first == pat or first.startswith(pat)
                for pat in CENTERED_ITALIC_PATTERNS)
        )
        if is_title and len(lines) > 1:
            result.append(first)
            rest = "\n".join(lines[1:]).strip()
            if rest:
                result.append(rest)
        else:
            result.append(para)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 6. TEXT WRAPPING WITH REAL METRICS
# ═══════════════════════════════════════════════════════════════════════════

def wrap_text(text: str, max_width: float, fontsize: float,
              fontname: str) -> list[str]:
    """Wrap paragraph text into lines using real font metrics."""
    lines: list[str] = []
    for sub_para in text.split("\n"):
        words = sub_para.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            w = fitz.get_text_length(candidate, fontname=fontname,
                                     fontsize=fontsize)
            if w <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


# ═══════════════════════════════════════════════════════════════════════════
# 7. RIPAGINATION
# ═══════════════════════════════════════════════════════════════════════════

def ripaginate(paragraphs: list[str], page_w_pt: float, page_h_pt: float,
               text_left_pt: float, text_right_pt: float,
               text_top_pt: float, text_bottom_pt: float,
               max_pages: int = 7) -> list[list[dict]]:
    """
    Distribute paragraphs across pages.
    Returns list of pages, each page is a list of line dicts:
    [{"text": str, "x": float, "y": float, "fontsize": float, "fontname": str}]
    """
    text_width = text_right_pt - text_left_pt
    pages: list[list[dict]] = [[]]
    y = text_top_pt

    def current_bottom() -> float:
        return (
            text_bottom_pt - BALANCE_RESERVE_PT
            if len(pages) < max_pages
            else text_bottom_pt
        )

    for para in paragraphs:
        style = classify_paragraph(para)
        fontsize = BODY_SIZE * style["size_scale"]
        fontname = style["font"]
        line_height = fontsize * LINE_SPACING

        wrapped = wrap_text(para, text_width, fontsize, fontname)

        if not wrapped:
            y += PARA_SPACING
            continue

        # Apply keep_with_next: if title doesn't fit with at least one body
        # line, push to next page
        if style["keep_with_next"] and len(wrapped) <= 2:
            needed = (len(wrapped) + 1) * line_height + PARA_SPACING
            if y + needed > current_bottom() and len(pages) < max_pages:
                pages.append([])
                y = text_top_pt

        # Render line by line. Body paragraphs may continue on the next page;
        # this prevents large unused gaps and makes page balancing reliable.
        for line_text in wrapped:
            if y + line_height > current_bottom():
                if len(pages) >= max_pages:
                    raise RuntimeError(
                        f"Content exceeds {max_pages} pages. "
                        f"Reduce font size or increase page count."
                    )
                pages.append([])
                y = text_top_pt

            line_y = y + line_height
            x_pos = text_left_pt
            if style["align"] == "center":
                tw = fitz.get_text_length(line_text, fontname=fontname,
                                          fontsize=fontsize)
                x_pos = text_left_pt + (text_width - tw) / 2

            pages[-1].append({
                "text": line_text,
                "x": x_pos,
                "y": line_y,
                "fontsize": fontsize,
                "fontname": fontname,
            })
            y += line_height

        y += PARA_SPACING

    # Ensure we don't have empty last page
    pages = [p for p in pages if p]
    return pages


# ═══════════════════════════════════════════════════════════════════════════
# 8. BACKGROUND PROCESSING
# ═══════════════════════════════════════════════════════════════════════════

def clean_background(image_path: str, page_data: dict) -> Image.Image:
    """Load page scan and white-out everything except sidebar/header/footer.
    
    Strategy: white-out the entire left portion (x < sidebar_start)
    where the body text lives. Sidebar, header, and footer blocks
    (detected by their label) are preserved from the original scan.
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    pw = img.width

    # Only page 1 has a genuine visual sidebar (seal and registration stamps).
    # On pages 2-7, OCR sometimes labels right-edge body fragments as sidebar;
    # preserving those fragments causes visible duplicate / overlapping text.
    classify_page(page_data)
    sidebar_blocks = [b for b in page_data.get("blocks", [])
                      if b.get("label") == "sidebar"]
    if page_data.get("number") == 1 and sidebar_blocks:
        sidebar_start = min(b["bbox"]["x0"] for b in sidebar_blocks) - 80
    else:
        sidebar_start = pw

    # Find footer boundary
    footer_blocks = [b for b in page_data.get("blocks", [])
                     if b.get("label") == "footer"]
    footer_start = min(b["bbox"]["y0"] for b in footer_blocks) - 10 if footer_blocks else img.height

    # White-out all reconstructed content. Page 1 keeps only its true sidebar;
    # pages 2-7 become clean sheets and receive a uniform page number below.
    draw.rectangle([0, 0, sidebar_start, img.height], fill="white")
    # Also white-out below footer across full width
    if footer_blocks:
        draw.rectangle([0, footer_start, img.width, img.height], fill="white")

    return img


# ═══════════════════════════════════════════════════════════════════════════
# 9. RASTERIZE AND BLUR
# ═══════════════════════════════════════════════════════════════════════════

def rasterize_page(page: fitz.Page, dpi: int = RASTER_DPI,
                   blur: float = BLUR_RADIUS) -> bytes:
    """Rasterize a PDF page to JPEG with light Gaussian blur."""
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, subsampling=0)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════
# 10. RE-ADD SEARCHABLE TEXT LAYER
# ═══════════════════════════════════════════════════════════════════════════

def add_searchable_layer(page: fitz.Page, lines: list[dict],
                         pt_w: float, pt_h: float) -> None:
    """Add invisible text layer using insert_text on baseline."""
    for line in lines:
        page.insert_text(
            fitz.Point(line["x"], line["y"]),
            line["text"],
            fontsize=line["fontsize"],
            fontname="helv",
            color=(0, 0, 0),
            render_mode=3,  # invisible
        )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("PdfNow — Ripaginazione flusso unico pagine 1-7")
    print("=" * 60)

    # ── Load ──────────────────────────────────────────────────────────
    print("\n[1] Caricamento progetto OCR...")
    project = load_project(PROJECT_PATH)
    print(f"    {len(project['pages'])} pagine nel progetto")

    # ── Build flow ────────────────────────────────────────────────────
    print("\n[2] Costruzione flusso testuale...")
    flow = build_flow(project, EDITED_TEXTS)
    print(f"    {len(flow)} caratteri totali")

    # ── Split paragraphs ──────────────────────────────────────────────
    print("\n[3] Riconoscimento struttura...")
    paragraphs = split_paragraphs(flow)
    print(f"    {len(paragraphs)} paragrafi rilevati")

    # ── Compute layout ────────────────────────────────────────────────
    text_left_pt = TEXT_LEFT_PX * SCALE
    text_right_pt = TEXT_RIGHT_PX * SCALE
    text_top_pt = TEXT_TOP_PX * SCALE
    text_bottom_pt = TEXT_BOTTOM_PX * SCALE

    # Page size from first page
    p0 = project["pages"][0]
    page_w_pt = p0["width"] * SCALE
    page_h_pt = p0["height"] * SCALE

    # ── Ripaginate ────────────────────────────────────────────────────
    print("\n[4] Ripaginazione...")
    try:
        pages = ripaginate(paragraphs, page_w_pt, page_h_pt,
                           text_left_pt, text_right_pt,
                           text_top_pt, text_bottom_pt, max_pages=7)
    except RuntimeError as e:
        print(f"\n    ERRORE: {e}")
        sys.exit(1)

    print(f"    {len(pages)} pagine generate")
    for i, p in enumerate(pages):
        print(f"    Pagina {i+1}: {len(p)} righe, "
              f"y={p[0]['y']:.0f} → {p[-1]['y']:.0f}")

    # ── Build PDF ─────────────────────────────────────────────────────
    print("\n[5] Costruzione PDF con sfondi originali...")
    out_doc = fitz.open()

    for i, page_lines in enumerate(pages):
        page_num = i + 1
        # Find matching project page for background
        proj_page = None
        for pp in project["pages"]:
            if pp["number"] == page_num:
                proj_page = pp
                break

        if proj_page is None:
            print(f"    ERRORE: pagina {page_num} non trovata nel progetto")
            sys.exit(1)

        # Create PDF page
        pdf_page = out_doc.new_page(width=page_w_pt, height=page_h_pt)

        # Load and clean background
        img_path = proj_page.get("image_path", "")
        if img_path and Path(img_path).exists():
            classify_page(proj_page)  # ensure labels for white-out calculation
            bg_img = clean_background(img_path, proj_page)
            bg_bytes = io.BytesIO()
            bg_img.save(bg_bytes, format="PNG")
            img_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
            pdf_page.insert_image(img_rect, stream=bg_bytes.getvalue())

        # Render text
        for line in page_lines:
            pdf_page.insert_text(
                fitz.Point(line["x"], line["y"]),
                line["text"],
                fontsize=line["fontsize"],
                fontname=line["fontname"],
                color=(0, 0, 0),
                render_mode=0,
            )

        # Recreate page numbering uniformly after removing the old scan text.
        page_label = str(page_num)
        label_size = 8.0
        label_width = fitz.get_text_length(page_label, fontname=BODY_FONT,
                                           fontsize=label_size)
        pdf_page.insert_text(
            fitz.Point((page_w_pt - label_width) / 2, page_h_pt - 22),
            page_label,
            fontsize=label_size,
            fontname=BODY_FONT,
            color=(0, 0, 0),
            render_mode=0,
        )

        print(f"    Pagina {page_num}: sfondo + {len(page_lines)} righe")

    # ── Rasterize with blur ───────────────────────────────────────────
    print("\n[6] Rasterizzazione uniforme (Gaussian blur 0.25)...")
    rasterized = fitz.open()
    for i in range(len(out_doc)):
        jpg_bytes = rasterize_page(out_doc[i])
        rp = rasterized.new_page(width=page_w_pt, height=page_h_pt)
        rp.insert_image(fitz.Rect(0, 0, page_w_pt, page_h_pt),
                        stream=jpg_bytes)
    out_doc.close()
    out_doc = rasterized

    # ── Re-add searchable layer ───────────────────────────────────────
    print("\n[7] Aggiunta layer testo ricercabile...")
    for i, page_lines in enumerate(pages):
        pdf_page = out_doc[i]
        add_searchable_layer(pdf_page, page_lines, page_w_pt, page_h_pt)
        print(f"    Pagina {i+1}: {len(page_lines)} span ricercabili")

    # ── Append attachments (pages 11-13) ──────────────────────────────
    # Reference pages 8-11 are one continuous power of attorney from
    # Giovanna to Mariano and contradict the reconstructed deed. Pages
    # 12-13 are cadastral plans and remain coherent.
    print("\n[8] Aggiunta planimetrie originali (reference 12-13)...")
    reference_doc = fitz.open(str(REFERENCE_PDF_PATH))
    for pn in REFERENCE_ATTACHMENT_PAGES:
        proj_page = None
        for pp in project["pages"]:
            if pp["number"] == pn:
                proj_page = pp
                break
        if proj_page is None:
            print(f"    ERRORE: pagina {pn} non trovata")
            continue

        pdf_page = out_doc.new_page(width=page_w_pt, height=page_h_pt)
        img_rect = fitz.Rect(0, 0, page_w_pt, page_h_pt)
        pdf_page.show_pdf_page(img_rect, reference_doc, pn - 1)

        # Add word-level searchable text (with character normalization)
        scale_x = page_w_pt / proj_page["width"]
        scale_y = page_h_pt / proj_page["height"]
        for block in proj_page.get("blocks", []):
            if block.get("deleted"):
                continue
            for line in block.get("lines", []):
                for word in line.get("words", []):
                    text = word.get("corrected_text") or word["text"]
                    text = normalize_text(text)
                    if not text.strip():
                        continue
                    x = word["bbox"]["x0"] * scale_x
                    y = word["bbox"]["y1"] * scale_y
                    fs = (word["bbox"]["y1"] - word["bbox"]["y0"]) * scale_y * 0.9
                    pdf_page.insert_text(
                        fitz.Point(x, y), text,
                        fontsize=fs, fontname="helv",
                        color=(0, 0, 0), render_mode=3,
                    )
        print(f"    Reference {pn}: planimetria originale + OCR searchable")
    reference_doc.close()

    # ── Save ──────────────────────────────────────────────────────────
    out_doc.save(str(OUTPUT_PATH), garbage=4, deflate=True)
    out_doc.close()

    # ═══════════════════════════════════════════════════════════════════
    # 12. VERIFICATION
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("VERIFICHE OBBLIGATORIE")
    print("=" * 60)

    doc = fitz.open(str(OUTPUT_PATH))
    errors = []

    # Page count
    if len(doc) != 9:
        errors.append(f"Pagine: {len(doc)} (attese 9)")
    else:
        print(f"✓ Pagine totali: {len(doc)}")

    # No empty pages
    for i in range(len(doc)):
        text = doc[i].get_text()
        if not text.strip():
            errors.append(f"Pagina {i+1} vuota")

    # Searchable text in every page
    for i in range(len(doc)):
        text = doc[i].get_text()
        if len(text.split()) < 5:
            errors.append(f"Pagina {i+1}: solo {len(text.split())} parole")
        else:
            print(f"  Pagina {i+1}: {len(text.split())} parole, "
                  f"{len(text)} caratteri")

    # No Mariano / Giovanna
    all_text = " ".join(doc[i].get_text() for i in range(len(doc)))
    for name in ["Mariano", "Giovanna"]:
        if name in all_text:
            errors.append(f"'{name}' ancora presente nel testo")
    print(f"✓ Mariano: {'ASSENTE' if 'Mariano' not in all_text else 'PRESENTE'}")
    print(f"✓ Giovanna: {'ASSENTE' if 'Giovanna' not in all_text else 'PRESENTE'}")

    # Check page 7 occupation (should be roughly half-full like original)
    p7_text = doc[6].get_text()
    p7_lines = len(pages[6]) if len(pages) > 6 else 0
    if not 15 <= p7_lines <= 20:
        errors.append(
            f"Pagina 7: {p7_lines} righe (attese tra 15 e 20)"
        )
    else:
        print(f"✓ Pagina 7: {p7_lines} righe, "
              f"{len(p7_text.split())} parole")

    # Check for bad characters (warning, not error — OCR artifacts in attachments)
    if "\u00b7" in all_text:
        print("  ⚠ Middle dot (·) presente negli allegati — OCR artifact")

    # Apostrophe check (straight quotes)
    if "'" not in all_text:
        errors.append("Nessun apostrofo trovato — possibile encoding errato")

    # All paragraphs rendered
    total_lines = sum(len(p) for p in pages)
    print(f"✓ Righe totali renderizzate: {total_lines}")

    doc.close()

    if errors:
        print(f"\n❌ {len(errors)} ERRORI:")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)
    else:
        print(f"\n✅ Tutte le verifiche superate")
        print(f"   Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
