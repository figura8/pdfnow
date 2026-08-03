import json

with open("export/atto_13p.json", encoding="utf-8") as f:
    doc = json.load(f)

for p in [8, 9, 10]:
    page = doc["pages"][p - 1]
    for block in page["blocks"]:
        block["deleted"] = True
    print(f"Pagina {p}: {len(page['blocks'])} blocchi eliminati")

with open("export/atto_13p.json", "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)

print("JSON aggiornato.")
