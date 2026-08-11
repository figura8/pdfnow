"""Final render: Francesco Esposito signature with user-chosen parameters.

erode=2  gamma=1.5  blur=0.7  ink=(77,77,77)
"""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ── Paths ───────────────────────────────────────────────────────────────────
PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

TARGET_DPI = 300
SOURCE_DPI = 96
SCALE = TARGET_DPI / SOURCE_DPI  # 3.125

PLACE_X = 952
PLACE_Y = 2342

JPEG_QUALITY = 90

# ── User-chosen parameters ──────────────────────────────────────────────────
ERODE_PX = 2
GAMMA = 1.5
BLUR = 0.7
INK_COLOR = (77, 77, 77)


def build_alpha(sig_path: Path, scale: float, erode_px: int = 0) -> Image.Image:
    im = Image.open(sig_path).convert("L")
    pixels = np.asarray(im, dtype=np.float32)
    bg = float(np.percentile(pixels, 95))
    ink = float(np.percentile(pixels, 2))
    alpha = np.clip((bg - pixels) / max(bg - ink, 1.0), 0.0, 1.0)
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))

    if erode_px > 0:
        arr = np.asarray(alpha_img)
        _, binary = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        eroded = cv2.erode(binary, kernel, iterations=erode_px)
        alpha_eroded = np.asarray(eroded, dtype=np.float32) / 255.0
        alpha_orig = arr.astype(np.float32) / 255.0
        alpha_blend = alpha_orig * alpha_eroded
        alpha_img = Image.fromarray((alpha_blend * 255).astype(np.uint8), "L")

    tw = round(im.width * scale)
    th = round(im.height * scale)
    return alpha_img.resize((tw, th), Image.Resampling.LANCZOS)


def composite(
    page: Image.Image,
    alpha: Image.Image,
    x: int, y: int,
    gamma: float,
    blur: float,
    ink_color: tuple[int, int, int],
) -> Image.Image:
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0.0, 1.0), gamma)
    arr = np.clip(arr, 0.0, 1.0)
    alpha_mod = Image.fromarray((arr * 255).astype(np.uint8), "L")
    if blur > 0:
        alpha_mod = alpha_mod.filter(ImageFilter.GaussianBlur(radius=blur))

    fg = Image.new("RGBA", alpha.size, (*ink_color, 255))
    fg.putalpha(alpha_mod)

    layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
    layer.alpha_composite(fg, dest=(x, y))
    bg_rgba = page.convert("RGBA")
    return Image.alpha_composite(bg_rgba, layer).convert("RGB")


def scanner_noise(image: Image.Image, box: tuple, seed: int = 42) -> Image.Image:
    rng = np.random.default_rng(seed)
    src = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = src.shape[:2]
    noise = rng.normal(0, 1.0, (h, w, 1))
    row_noise = rng.normal(0, 0.15, (h, 1, 1))
    processed = np.clip(src + noise + row_noise, 0, 255)

    x0, y0, x1, y1 = box
    margin = 30
    fx0, fy0 = max(0, x0 - margin), max(0, y0 - margin)
    fx1, fy1 = min(w, x1 + margin), min(h, y1 + margin)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle((fx0, fy0, fx1, fy1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=12))
    alpha_n = np.asarray(mask, dtype=np.float32)[..., None] / 255.0
    result = src * (1.0 - alpha_n) + processed * alpha_n
    return Image.fromarray(result.astype(np.uint8), "RGB")


def jpeg_bake(image: Image.Image, quality: int = JPEG_QUALITY) -> Image.Image:
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=quality, subsampling=2, optimize=False)
    buf.seek(0)
    return Image.open(buf).copy()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Parameters: erode={ERODE_PX} gamma={GAMMA} blur={BLUR} ink={INK_COLOR}")

    print("Loading page...")
    page = Image.open(PAGE_PATH).convert("RGB")
    print(f"  Page: {page.size}")

    print("Building alpha mask with erosion...")
    alpha = build_alpha(SIG_PATH, SCALE, erode_px=ERODE_PX)
    print(f"  Alpha: {alpha.size}")

    print("Compositing...")
    comp = composite(page, alpha, PLACE_X, PLACE_Y, GAMMA, BLUR, INK_COLOR)

    sig_box = (PLACE_X, PLACE_Y, PLACE_X + alpha.width, PLACE_Y + alpha.height)
    print("Adding scanner noise...")
    noisy = scanner_noise(comp, box=sig_box)

    print("JPEG bake...")
    final = jpeg_bake(noisy)

    # ── Save ────────────────────────────────────────────────────────────────
    final_jpg = OUT_DIR / "firma_francesco_final.jpg"
    final_png = OUT_DIR / "firma_francesco_final.png"
    final.save(final_jpg, quality=JPEG_QUALITY, subsampling=2, dpi=(TARGET_DPI, TARGET_DPI))
    final.save(final_png, dpi=(TARGET_DPI, TARGET_DPI))

    # Comparison crop: before/after
    margin = 100
    crop_box = (
        max(0, PLACE_X - margin),
        max(0, PLACE_Y - 30),
        min(page.width, PLACE_X + alpha.width + margin),
        min(page.height, PLACE_Y + alpha.height + 30),
    )
    before = page.crop(crop_box)
    after = final.crop(crop_box)
    comp_img = Image.new("RGB", (before.width * 2 + 4, before.height))
    comp_img.paste(before, (0, 0))
    comp_img.paste(Image.new("RGB", (4, before.height), (0, 180, 0)), (before.width, 0))
    comp_img.paste(after, (before.width + 4, 0))
    comp_path = OUT_DIR / "firma_francesco_comparison.png"
    comp_img.save(comp_path)

    print(f"\nDone!")
    print(f"  {final_jpg}")
    print(f"  {final_png}")
    print(f"  {comp_path}")


if __name__ == "__main__":
    main()
