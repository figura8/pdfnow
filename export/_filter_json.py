import json, copy

with open("export/atto_13p.json", encoding="utf-8") as f:
    doc = json.load(f)

# Keep only unmodified pages: 2, 4, 6, 11, 12, 13
keep = {2, 4, 6, 11, 12, 13}
filtered = copy.deepcopy(doc)
filtered["pages"] = [p for p in doc["pages"] if p["number"] in keep]

with open("export/atto_unmodified.json", "w", encoding="utf-8") as f:
    json.dump(filtered, f, indent=2, ensure_ascii=False)

print(f"Pagine esportate: {[p['number'] for p in filtered['pages']]}")
