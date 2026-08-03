"""Merge rebuilt and searchable pages into the final PDF."""
import fitz

final = fitz.open()

# Order: 1(rebuild), 2(searchable), 3(rebuild), 4(searchable), 5(rebuild),
#        6(searchable), 7(rebuild), 11(searchable), 12(searchable), 13(searchable)

# Rebuilt pages (single-page PDFs)
for pdf_path in [
    "export/atto_p1.pdf",
    "export/atto_p3.pdf",
    "export/atto_p5.pdf",
    "export/atto_p7.pdf",
]:
    src = fitz.open(pdf_path)
    final.insert_pdf(src)
    src.close()

# Searchable unmodified pages
# Filtered JSON had pages [2, 4, 6, 11, 12, 13] → positions 0-5 in the PDF
searchable = fitz.open("export/atto_searchable_unmod.pdf")
# Extract in the right positions for merge:
# Need: p2(pos0), p4(pos1), p6(pos2), skip p8-10, p11(pos3), p12(pos4), p13(pos5)
# Insert into final following the rebuilt pages: after p1→p2, after p3→p4, after p5→p6,
# after p7→p11,p12,p13

# We build final as:
# [p1_reb, p2(0), p3_reb, p4(1), p5_reb, p6(2), p7_reb, p11(3), p12(4), p13(5)]

# The rebuilt pages are already in final (positions 0,2,4,6)
# Now insert searchable pages at their correct positions

# Actually, final currently has: [p1, p3, p5, p7] at positions 0,1,2,3
# We need: [p1, p2, p3, p4, p5, p6, p7, p11, p12, p13]
# Insert searchable pages at positions 1, 3, 5, then append 8,9,10

# Insert p2 at position 1 (after p1)
final.insert_pdf(searchable, from_page=0, to_page=0, start_at=1)
# Now final = [p1, p2, p3, p5, p7]

# Insert p4 at position 3
final.insert_pdf(searchable, from_page=1, to_page=1, start_at=3)
# Now final = [p1, p2, p3, p4, p5, p7]

# Insert p6 at position 5
final.insert_pdf(searchable, from_page=2, to_page=2, start_at=5)
# Now final = [p1, p2, p3, p4, p5, p6, p7]

# Append remaining: p11, p12, p13 (positions 3,4,5 in searchable)
final.insert_pdf(searchable, from_page=3, to_page=5)

searchable.close()

final.save("export/atto_finale.pdf", garbage=4, deflate=True)
final.close()

# Verify
doc = fitz.open("export/atto_finale.pdf")
print(f"Pagine totali: {len(doc)}")
for i in range(len(doc)):
    text = doc[i].get_text()
    words = len(text.split())
    print(f"  Pagina {i+1}: {words} parole, {len(text)} caratteri")
doc.close()
