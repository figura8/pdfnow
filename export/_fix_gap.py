"""Fix page 3 layout: remove white gap from Art.3 redaction."""
import fitz
from PIL import Image
import numpy as np

INPUT = r"c:\Users\maurizio\Documents\pdfnow\export\atto_v5_p1clean_p8_noart3.pdf"
OUTPUT = r"c:\Users\maurizio\Documents\pdfnow\export\atto_v5_p1clean_p8_noart3_fixed.pdf"

doc = fitz.open(INPUT)
page = doc[2]  # page 3

mat = fitz.Matrix(300/72, 300/72)
pix = page.get_pixmap(matrix=mat)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

arr = np.array(img.convert("L"))
h, w = arr.shape

row_means = arr.mean(axis=1)
white_rows = row_means > 250
mid_start, mid_end = h // 4, 3 * h // 4
white_in_mid = np.where(white_rows[mid_start:mid_end])[0]

if len(white_in_mid) > 0:
    gap_start = mid_start + white_in_mid[0]
    gap_end = mid_start + white_in_mid[-1]
    print(f"Gap: rows {gap_start}-{gap_end} ({gap_end-gap_start}px)")

    top = arr[:gap_start]
    bottom = arr[gap_end:]

    small_gap = 20
    new_arr = np.full_like(arr, 255)
    new_arr[:len(top)] = top
    new_arr[len(top) + small_gap:len(top) + small_gap + len(bottom)] = bottom

    new_img = Image.fromarray(new_arr, "L")

    # Save as temp PNG and use fitz.open
    tmp_path = r"c:\Users\maurizio\Documents\pdfnow\export\_tmp_page3.png"
    new_img.save(tmp_path)

    png_doc = fitz.open(tmp_path)
    pdf_bytes = png_doc.convert_to_pdf()
    png_doc.close()

    doc.delete_page(2)
    doc.insert_pdf(fitz.open("pdf", pdf_bytes), start_at=2)
    doc.save(OUTPUT)
    print(f"Saved: {OUTPUT}")

    import os
    os.remove(tmp_path)
else:
    print("No gap detected")

doc.close()
