import json

with open("export/atto_13p.json", encoding="utf-8") as f:
    doc = json.load(f)

# Search for words containing 4A or · (any form)
for page in doc["pages"]:
    for block in page["blocks"]:
        for line in block.get("lines", []):
            for word in line.get("words", []):
                t = word["text"]
                if "4A" in t or "\u00b7" in t or "·" in t:
                    chars = " ".join(f"U+{ord(c):04X}" for c in t)
                    print(f"P{page['number']}: '{t}' -> {chars}")


