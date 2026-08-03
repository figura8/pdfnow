"""Build the final mixed document with scan-like rebuilt pages.

Rebuilt pages are rasterized at 300 DPI and receive a fresh invisible text
layer. Untouched pages are copied from the searchable source PDF.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "export"
OUTPUT = EXPORT / "atto_finale_uniforme.pdf"
RENDER_DPI = 300
BLUR_RADIUS = 0.25


def add_rasterized_rebuilt_page(target: fitz.Document, source_path: Path) -> None:
    """Rasterize one rebuilt page and restore an invisible searchable layer."""
    with fitz.open(source_path) as source:
        source_page = source[0]
        text_dict = source_page.get_text("dict")
        matrix = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
        pixmap = source_page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)

        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        image = image.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        image_buffer = BytesIO()
        image.save(image_buffer, format="JPEG", quality=92, subsampling=0, dpi=(RENDER_DPI, RENDER_DPI))

        output_page = target.new_page(
            width=source_page.rect.width,
            height=source_page.rect.height,
        )
        output_page.insert_image(output_page.rect, stream=image_buffer.getvalue())

        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if not text.strip():
                        continue
                    origin = span.get("origin")
                    if not origin:
                        continue
                    output_page.insert_text(
                        fitz.Point(*origin),
                        text,
                        fontsize=max(1.0, float(span.get("size", 9.7))),
                        fontname="helv",
                        render_mode=3,
                    )


def main() -> None:
    rebuilt = {
        1: EXPORT / "atto_p1_uniform.pdf",
        3: EXPORT / "atto_p3_uniform.pdf",
        5: EXPORT / "atto_p5_uniform.pdf",
        7: EXPORT / "atto_p7_uniform.pdf",
    }
    untouched_positions = {2: 0, 4: 1, 6: 2, 11: 3, 12: 4, 13: 5}

    missing = [str(path) for path in rebuilt.values() if not path.exists()]
    searchable_path = EXPORT / "atto_searchable_unmod.pdf"
    if not searchable_path.exists():
        missing.append(str(searchable_path))
    if missing:
        raise FileNotFoundError("Missing merge input(s): " + ", ".join(missing))

    final = fitz.open()
    with fitz.open(searchable_path) as searchable:
        for original_page_number in (1, 2, 3, 4, 5, 6, 7, 11, 12, 13):
            if original_page_number in rebuilt:
                add_rasterized_rebuilt_page(final, rebuilt[original_page_number])
            else:
                position = untouched_positions[original_page_number]
                final.insert_pdf(searchable, from_page=position, to_page=position)

    final.set_metadata({
        "title": "Atto notarile - versione uniforme",
        "producer": "PdfNow",
    })
    final.save(OUTPUT, garbage=4, deflate=True)
    final.close()

    with fitz.open(OUTPUT) as check:
        print(f"Creato {OUTPUT}: {check.page_count} pagine")
        for index, page in enumerate(check):
            print(
                f"  Pagina {index + 1}: {len(page.get_text())} caratteri, "
                f"{len(page.get_images(full=True))} immagine/i"
            )


if __name__ == "__main__":
    main()
