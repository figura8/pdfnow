"""Check page 3 structure and find Art. 3 coordinates."""
import fitz

doc = fitz.open(r"c:\Users\maurizio\Documents\pdfnow\export\atto_v5_p1clean_p8.pdf")
page = doc[2]  # page 3

print(f"Images: {len(page.get_images())}")
print(f"Page size: {page.rect.width:.0f}x{page.rect.height:.0f}")

# Find Art.3 and Art.4 positions
d = page.get_text("dict")
for block in d["blocks"]:
    if "lines" not in block:
        continue
    for line in block["lines"]:
        text = "".join(s["text"] for s in line["spans"])
        if "Art.3" in text or "Art.4" in text:
            bbox = line["bbox"]
            print(f"  '{text[:80]}' -> ({bbox[0]:.0f},{bbox[1]:.0f})-({bbox[2]:.0f},{bbox[3]:.0f})")

# Show all lines with coordinates
for block in d["blocks"]:
    if "lines" not in block:
        continue
    for line in block["lines"]:
        text = "".join(s["text"] for s in line["spans"]).strip()
        if text:
            bbox = line["bbox"]
            print(f"  y={bbox[1]:.0f}: {text[:100]}")

doc.close()
