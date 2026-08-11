"""Quick final renders at dt=2.5 and dt=3.0 for direct comparison on the page."""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 300 / 96
PLACE_X, PLACE_Y = 952, 2342
INK_COLOR = (77, 77, 77)


def build_dt_alpha(sig_path: Path, scale: float, dt: float) -> Image.Image:
    im = Image.open(sig_path).convert("L")
    src = np.asarray(im, dtype=np.float32)
    bg = float(np.percentile(src, 95))
    ink = float(np.percentile(src, 2))
    alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)
    binary = (alpha > 0.5).astype(np.uint8) * 255
    if binary.sum() < 10:
        tw, th = round(im.width * scale), round(im.height * scale)
        return Image.new("L", (tw, th), 0)

    dist = cv2.distanceTransform(binary, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    thinned = (dist > dt).astype(np.uint8) * 255

    # Use binary mask directly + tiny blur for anti-aliasing
    result = thinned.astype(np.float32) / 255.0
    alpha_img = Image.fromarray((result * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.3))

    tw, th = round(im.width * scale), round(im.height * scale)
    return alpha_img.resize((tw, th), Image.Resampling.LANCZOS)


def composite(page, alpha, x, y, gamma, blur, ink):
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0, 1), gamma)
    alpha_mod = Image.fromarray((arr * 255).astype(np.uint8), "L")
    if blur > 0:
        alpha_mod = alpha_mod.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", alpha.size, (*ink, 255))
    fg.putalpha(alpha_mod)
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

    for dt, gamma, blur, label in [
        (2.5, 1.0, 0.7, "dt25"),
        (3.0, 1.0, 0.7, "dt30"),
    ]:
        print(f"Rendering {label}...")
        alpha = build_dt_alpha(SIG_PATH, SCALE, dt)
        comp = composite(page, alpha, PLACE_X, PLACE_Y, gamma, blur, INK_COLOR)
        box = (PLACE_X, PLACE_Y, PLACE_X + alpha.width, PLACE_Y + alpha.height)
        noisy = scanner_noise(comp, box)
        final = jpeg_bake(noisy)
        final.save(OUT_DIR / f"firma_dt_{label}.png", dpi=(300, 300))
        final.save(OUT_DIR / f"firma_dt_{label}.jpg", quality=90, subsampling=2, dpi=(300, 300))
        print(f"  -> firma_dt_{label}.png")

    print("Done!")


if __name__ == "__main__":
    main()
