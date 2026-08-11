"""Power-curve thinning informed by campione_tratto.png analysis.

Profile findings: edge transition 4px, FWHM 22px → edges are SHARP
(ratio 0.18).  Minimal blur needed.  Noise σ ≈ 5.5 at sample resolution.
"""
from __future__ import annotations
import io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma3.png")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 0.35
PLACE_X, PLACE_Y = 952, 2342
INK_COLOR = (77, 77, 77)


def build_alpha(sig_path, scale):
    im = Image.open(sig_path)
    src = np.asarray(im.convert("RGB")).mean(axis=2).astype(np.float32)
    bg = float(np.percentile(src, 95))
    ink = float(np.percentile(src, 2))
    alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))
    tw, th = round(im.width * scale), round(im.height * scale)
    alpha_img = alpha_img.resize((tw, th), Image.Resampling.LANCZOS)
    return np.asarray(alpha_img, dtype=np.float32) / 255.0


def composite_page(page, alpha_arr, x, y, blur, ink):
    img = Image.fromarray((alpha_arr * 255).astype(np.uint8), "L")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", img.size, (*ink, 255))
    fg.putalpha(img)
    layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
    layer.alpha_composite(fg, dest=(x, y))
    return Image.alpha_composite(page.convert("RGBA"), layer).convert("RGB")


def scanner_noise(image, box, seed=42):
    rng = np.random.default_rng(seed)
    src = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = src.shape[:2]
    noise = rng.normal(0, 1.0, (h, w, 1))
    row_noise = rng.normal(0, 0.15, (h, 1, 1))
    processed = np.clip(src + noise + row_noise, 0, 255)
    x0, y0, x1, y1 = box
    m = 30
    fx0, fy0 = max(0, x0-m), max(0, y0-m)
    fx1, fy1 = min(w, x1+m), min(h, y1+m)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle((fx0, fy0, fx1, fy1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=12))
    a = np.asarray(mask, dtype=np.float32)[..., None] / 255.0
    return Image.fromarray((src*(1-a) + processed*a).astype(np.uint8), "RGB")


def jpeg_bake(image, q=90):
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=q, subsampling=2, optimize=False)
    buf.seek(0)
    return Image.open(buf).copy()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page = Image.open(PAGE_PATH).convert("RGB")

    print("Building alpha mask...")
    alpha = build_alpha(SIG_PATH, SCALE)
    print(f"  Alpha: {alpha.shape[1]}x{alpha.shape[0]}")

    # Profile says: edges are SHARP (4px transition vs 22px FWHM).
    # → use minimal blur (0.0–0.2) and focused power range (2.5–3.5).
    for power, blur, label in [
        (2.8, 0.1,  "p28"),     # slightly thicker than pow30
        (3.0, 0.1,  "p30"),
        (3.2, 0.1,  "p32"),
        (3.0, 0.0,  "p30s"),    # sharp edges (no blur)
        (3.3, 0.0,  "p33s"),
    ]:
        print(f"Power={power} blur={blur}...")
        thinned = np.power(np.clip(alpha, 0, 1), power)

        # Add subtle noise matching sample texture
        rng = np.random.default_rng(7)
        noise = rng.normal(0, 0.03, thinned.shape)
        noise = np.asarray(Image.fromarray(
            (noise * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(3)), np.float32) / 255.0
        thinned = np.clip(thinned + noise * (thinned > 0.02), 0, 1)

        nz = int((thinned > 0.01).sum())
        print(f"  non-zero: {nz}")

        comp = composite_page(page, thinned, PLACE_X, PLACE_Y, blur, INK_COLOR)
        box = (PLACE_X, PLACE_Y, PLACE_X + thinned.shape[1], PLACE_Y + thinned.shape[0])
        noisy = scanner_noise(comp, box)
        final = jpeg_bake(noisy)
        final.save(OUT_DIR / f"firma3_{label}.png", dpi=(300, 300))

    print("Done!")


if __name__ == "__main__":
    main()
