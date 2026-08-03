"""OCR pipeline — extract text with coordinates and confidence scores.

Uses Tesseract via pytesseract as the default engine.
Supports pluggable engines via OCREngine protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytesseract
from PIL import Image

# Auto-detect Tesseract installation on Windows
import shutil
_tesseract_path = shutil.which("tesseract")
if _tesseract_path is None:
    # Common fallback locations
    _candidates = [
        r"C:\Users\maurizio\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    ]
    for _c in _candidates:
        if Path(_c).exists():
            pytesseract.pytesseract.tesseract_cmd = _c
            break
else:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_path

from .model import BBox, Block, BlockType, Document, Line, Page, Word
from .style import analyze_layout


class OCREngine(Protocol):
    """Protocol for OCR engines. Implement this to add new backends."""

    def recognize(self, image: Image.Image, lang: str = "ita") -> list[Block]:
        ...


class TesseractEngine:
    """OCR engine backed by Tesseract via pytesseract."""

    def __init__(self, lang: str = "ita", config: str = ""):
        self.lang = lang
        # --psm 3 = fully automatic page segmentation with orientation detection
        # --psm 6 = assume uniform block of text
        self.config = config or "--psm 3"

    def recognize(self, image: Image.Image, lang: str | None = None) -> list[Block]:
        """Run OCR on a PIL image and return blocks with coordinates."""
        lang = lang or self.lang

        # Get detailed data: word-level with bounding boxes and confidence
        data = pytesseract.image_to_data(
            image, lang=lang, config=self.config, output_type=pytesseract.Output.DICT
        )

        return self._parse_hocr_data(data, image.size)

    def _parse_hocr_data(self, data: dict, image_size: tuple[int, int]) -> list[Block]:
        """Parse Tesseract's image_to_data dict into our document model.

        Groups words into lines and lines into blocks using Tesseract's
        block_num / par_num / line_num hierarchy.
        """
        w, h = image_size
        n = len(data["text"])

        # Group words by (block_num, par_num, line_num)
        lines: dict[tuple[int, int, int], list[Word]] = {}
        blocks: dict[int, list[tuple[int, int]]] = {}  # block_num -> list of (par_num, line_num)

        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue

            raw_conf = data["conf"][i]
            conf = float(raw_conf) if str(raw_conf) != "-1" else 0.0
            confidence = max(0.0, min(1.0, conf / 100.0))

            block_num = data["block_num"][i]
            par_num = data["par_num"][i]
            line_num = data["line_num"][i]

            # Tesseract coordinates: left, top, width, height
            left = data["left"][i]
            top = data["top"][i]
            tw = data["width"][i]
            th = data["height"][i]

            word = Word(
                text=text,
                bbox=BBox(x0=left, y0=top, x1=left + tw, y1=top + th),
                confidence=confidence,
            )

            key = (block_num, par_num, line_num)
            lines.setdefault(key, []).append(word)
            blocks.setdefault(block_num, []).append((par_num, line_num))

        # Build lines grouped by block
        result: list[Block] = []

        for block_num in sorted(blocks):
            block_lines: list[Line] = []

            # Deduplicate and sort (par_num, line_num) pairs
            seen = set()
            for par_num, line_num in sorted(set(blocks[block_num])):
                key = (block_num, par_num, line_num)
                if key in lines and key not in seen:
                    seen.add(key)
                    block_lines.append(Line(words=lines[key]))

            if block_lines:
                # Compute block bbox as union of line bboxes
                block_bbox = BBox(
                    x0=min(l.bbox.x0 for l in block_lines),
                    y0=min(l.bbox.y0 for l in block_lines),
                    x1=max(l.bbox.x1 for l in block_lines),
                    y1=max(l.bbox.y1 for l in block_lines),
                )
                result.append(Block(bbox=block_bbox, lines=block_lines))

        return result


class OCRError(Exception):
    """Raised when OCR processing fails."""
    pass


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Apply standard pre-processing to improve OCR accuracy.

    - Convert to grayscale
    - Increase contrast with CLAHE (if available) or simple normalization
    - Binarize (Otsu threshold)
    """
    import cv2
    import numpy as np

    # PIL -> numpy
    img = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    # Denoise
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    # CLAHE for contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    # Otsu binarization
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return Image.fromarray(binary)


def run_ocr_on_pdf(
    pdf_path: str | Path,
    engine: OCREngine | None = None,
    preprocess: bool = True,
    lang: str = "ita",
    output_dir: str | Path | None = None,
    max_pages: int | None = None,
) -> Document:
    """Run OCR on every page of a scanned PDF.

    Args:
        pdf_path: Path to the scanned PDF.
        engine: OCR engine (defaults to Tesseract).
        preprocess: Apply image pre-processing before OCR.
        lang: Tesseract language code (ita, eng, fra, deu, etc.).
        output_dir: Where to save extracted page images (default: pdf_path.parent / .pdfnow).
        max_pages: Limit processing to the first N pages (None = all).

    Returns:
        A Document with all pages populated.
    """
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if output_dir is None:
        output_dir = pdf_path.parent / ".pdfnow" / pdf_path.stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if engine is None:
        engine = TesseractEngine(lang=lang)

    doc = fitz.open(str(pdf_path))
    document = Document(source_path=str(pdf_path))
    document.metadata = {
        "title": doc.metadata.get("title", ""),
        "author": doc.metadata.get("author", ""),
        "page_count": doc.page_count,
        "ocr_engine": type(engine).__name__,
        "ocr_lang": lang,
    }

    total_pages = min(doc.page_count, max_pages) if max_pages else doc.page_count

    for page_num in range(total_pages):
        page = doc[page_num]

        # Render page at 300 DPI for good OCR quality
        zoom = 300 / 72  # PDF default is 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Save page image
        img_filename = f"page_{page_num + 1:04d}.png"
        img_path = output_dir / img_filename
        img.save(str(img_path), "PNG")

        # Preprocess
        ocr_img = preprocess_for_ocr(img) if preprocess else img

        try:
            blocks = engine.recognize(ocr_img, lang=lang)
        except Exception as e:
            raise OCRError(f"OCR failed on page {page_num + 1}: {e}") from e

        document.pages.append(Page(
            number=page_num + 1,
            image_path=str(img_path),
            width=pix.width,
            height=pix.height,
            blocks=blocks,
        ))

        # Classify blocks as body/sidebar/header/footer right after OCR
        analyze_layout(document.pages[-1])

    doc.close()
    return document
