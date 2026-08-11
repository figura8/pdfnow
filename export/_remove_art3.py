"""Remove Art. 3 from page 3 using redaction."""
import fitz

doc = fitz.open(r"c:\Users\maurizio\Documents\pdfnow\export\atto_v5_p1clean_p8.pdf")
page = doc[2]

# Redact the Art.3 region
rect = fitz.Rect(60, 140, 560, 568)
page.add_redact_annot(rect, fill=(1, 1, 1))  # white fill
page.apply_redactions()

out = r"c:\Users\maurizio\Documents\pdfnow\export\atto_v5_p1clean_p8_noart3.pdf"
doc.save(out)
doc.close()

doc2 = fitz.open(out)
page2 = doc2[2]
text = page2.get_text()
print(f"Art.3: {'Art.3' in text}")
print(f"Art.4: {'Art.4' in text}")
print(f"Saved: {out}")
doc2.close()
