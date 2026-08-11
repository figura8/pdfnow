from PIL import Image
import numpy as np

img = Image.open(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
arr = np.array(img)

def sample_ink(arr, x0, y0, x1, y1, min_darkness=60):
    zone = arr[y0:y1, x0:x1]
    dark_mask = (zone.max(axis=2) < 180) & (zone.max(axis=2) > 30)
    if dark_mask.sum() < 10:
        return None
    pixels = zone[dark_mask]
    return {
        "mean": pixels.mean(axis=0),
        "median": np.median(pixels, axis=0),
        "std": pixels.std(axis=0),
        "count": len(pixels),
    }

areas = [
    ("left sig",  460, 3095, 540, 3165),
    ("right sig", 2140, 3095, 2260, 3165),
    ("text black ref", 300, 500, 500, 600),
]

for name, x0, y0, x1, y1 in areas:
    result = sample_ink(arr, x0, y0, x1, y1)
    if result:
        m = result["mean"]
        med = result["median"]
        print(f"{name}: mean=({m[0]:.0f},{m[1]:.0f},{m[2]:.0f}) median=({med[0]:.0f},{med[1]:.0f},{med[2]:.0f}) n={result['count']}")
    else:
        print(f"{name}: no ink found")

# Francesco's signature
sig = Image.open(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
sig_arr = np.array(sig)
dark_sig = (sig_arr.max(axis=2) < 180) & (sig_arr.max(axis=2) > 30)
if dark_sig.sum() > 0:
    sp = sig_arr[dark_sig]
    m = sp.mean(axis=0)
    med = np.median(sp, axis=0)
    print(f"firma.jpg ink: mean=({m[0]:.0f},{m[1]:.0f},{m[2]:.0f}) median=({med[0]:.0f},{med[1]:.0f},{med[2]:.0f})")
