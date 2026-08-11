"""Replace signature page (page 7) in atto_reference_francesco_v5.pdf
with the firma3_v22_p25 render."""
from pathlib import Path
import fitz

PDF_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\export\atto_reference_francesco_v5.pdf")
SIG_PAGE = Path(r"c:\Users\maurizio\Documents\pdfnow\export\firma3_v22_p25.png")
OUT_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\export\atto_finale_con_firma.pdf")

SIGNATURE_PAGE_INDEX = 6  # 0-based, page 7


def main():
    doc = fitz.open(str(PDF_PATH))
    print(f"PDF: {doc.page_count} pages")

    # Convert PNG to a single-page PDF
    sig_img = fitz.open(str(SIG_PAGE))
    sig_pdf_bytes = sig_img.convert_to_pdf()
    sig_img.close()

    # Delete old page 7 and insert new page
    print(f"Replacing page {SIGNATURE_PAGE_INDEX + 1}...")
    doc.delete_page(SIGNATURE_PAGE_INDEX)

    # Insert the PNG-derived PDF page at the same position
    doc.insert_pdf(fitz.open("pdf", sig_pdf_bytes),
                   start_at=SIGNATURE_PAGE_INDEX)

    doc.save(str(OUT_PATH))
    doc.close()

    # Verify
    result = fitz.open(str(OUT_PATH))
    print(f"Saved: {OUT_PATH}")
    print(f"Pages: {result.page_count}")
    result.close()


if __name__ == "__main__":
    main()
