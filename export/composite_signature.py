"""
Signature compositing pipeline — test harness for PdfNow.

Takes a scanned page image with a blank area and composites a new
handwritten element (from a lower-DPI JPEG), preserving the visual
characteristics of a real 300 DPI scan.

Sources: immagine2.png (page with blank area) + firma.jpg (element to place)
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ── Parameters ──────────────────────────────────────────────────────────────
PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SOURCE_DPI   = 96
TARGET_DPI   = 300
SCALE        = TARGET_DPI / SOURCE_DPI          # ≈ 3.125

# Position (top-left corner on the full page, in 300 DPI pixels)
PLACE_X = 952
PLACE_Y = 2342

# Scanner simulation
NOISE_SIGMA  = 1.0      # luminance noise σ (0.5–1.5 typical)
JPEG_QUALITY = 90

# Pre/post blur for the alpha mask
PRE_BLUR_RADIUS  = 0.15   # suppress JPEG artefacts before upscale
POST_BLUR_RADIUS = 0.5    # suppress Lanczos ringing after upscale

# ── Step 1: build continuous alpha mask from luminance ──────────────────────
def build_alpha_mask(sig_path: Path, scale: float) -> Image.Image:
    """Convert stroke darkness into a continuous alpha/coverage mask.

    Light JPEG background -> 0 (transparent), dark ink -> 1 (opaque).
    Uses the full background-ink range so tonal variation is preserved.
    """
    im = Image.open(sig_path).convert("L")
    pixels = np.asarray(im, dtype=np.float32)

    # Estimate paper/background from bright pixels.
    bg = float(np.percentile(pixels, 95))

    # Estimate darkest ink from percentile (to ignore pure black specks).
    ink = float(np.percentile(pixels, 2))

    # Normalise: 0 at bg, 1 at ink.  Avoid division by zero.
    denom = max(bg - ink, 1.0)
    alpha = np.clip((bg - pixels) / denom, 0.0, 1.0)

    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")

    # Optional micro-blur to suppress JPEG mosquito noise.
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=PRE_BLUR_RADIUS))

    # Upscale to target DPI.
    target_w = round(im.width * scale)
    target_h = round(im.height * scale)
    alpha_img = alpha_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Post-scale blur to suppress Lanczos ringing.
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=POST_BLUR_RADIUS))

    return alpha_img


# ── Step 2: upscale the RGB foreground ──────────────────────────────────────
def upscale_foreground(sig_path: Path, scale: float) -> Image.Image:
    """Upscale the signature RGB to target DPI via Lanczos."""
    im = Image.open(sig_path).convert("RGB")

    # Tiny pre-blur to suppress JPEG artefacts before upscaling.
    im = im.filter(ImageFilter.GaussianBlur(radius=PRE_BLUR_RADIUS))

    target_w = round(im.width * scale)
    target_h = round(im.height * scale)
    return im.resize((target_w, target_h), Image.Resampling.LANCZOS)


# ── Step 3: composite foreground onto the page ──────────────────────────────
def composite_onto_page(
    page: Image.Image,
    fg: Image.Image,
    alpha: Image.Image,
    x: int,
    y: int,
) -> Image.Image:
    """Alpha-composite the foreground element at (x, y) on the page."""
    fg_rgba = fg.convert("RGBA")
    fg_rgba.putalpha(alpha)

    # Create a transparent layer the size of the page, place fg on it.
    layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
    layer.alpha_composite(fg_rgba, dest=(x, y))

    bg_rgba = page.convert("RGBA")
    result = Image.alpha_composite(bg_rgba, layer)
    return result.convert("RGB")


# ── Step 4: scanner noise simulation ────────────────────────────────────────
def scanner_effect(
    image: Image.Image,
    box: tuple[int, int, int, int] | None = None,
    sigma: float = NOISE_SIGMA,
    seed: int = 42,
) -> Image.Image:
    """Add subtle luminance noise + weak row banding, typical of a CCD scanner.

    If *box* is provided, noise is applied only inside that region with a
    feathered edge mask to avoid visible seams.
    """
    rng = np.random.default_rng(seed)
    src = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = src.shape[:2]

    # Luminance noise shared across RGB channels.
    noise = rng.normal(0, sigma, (h, w, 1))

    # Very weak row banding (scanner line noise).
    row_noise = rng.normal(0, 0.15, (h, 1, 1))

    processed = np.clip(src + noise + row_noise, 0, 255)

    if box is None:
        result = processed
    else:
        x0, y0, x1, y1 = box
        # Expand box slightly for feathering margin.
        margin = 30
        fx0 = max(0, x0 - margin)
        fy0 = max(0, y0 - margin)
        fx1 = min(w, x1 + margin)
        fy1 = min(h, y1 + margin)

        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rectangle((fx0, fy0, fx1, fy1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=12))
        alpha = np.asarray(mask, dtype=np.float32)[..., None] / 255.0
        result = src * (1.0 - alpha) + processed * alpha

    return Image.fromarray(result.astype(np.uint8), "RGB")


# ── Step 5: JPEG bake (save + reload to embed DCT artefacts) ────────────────
def jpeg_bake(image: Image.Image, quality: int = JPEG_QUALITY) -> Image.Image:
    """Save to JPEG in-memory and reload to bake compression artefacts into pixels."""
    buf = io.BytesIO()
    image.save(
        buf,
        "JPEG",
        quality=quality,
        subsampling=2,         # 4:2:0 chroma subsampling (typical scanner)
        optimize=False,
        dpi=(TARGET_DPI, TARGET_DPI),
    )
    buf.seek(0)
    return Image.open(buf).copy()


# ── Main pipeline ───────────────────────────────────────────────────────────
def main() -> None:
    print("Loading page...")
    page = Image.open(PAGE_PATH).convert("RGB")
    print(f"  Page: {page.size}, {page.info.get('dpi', 'no DPI')}")

    print("Building alpha mask & upscaling foreground...")
    alpha = build_alpha_mask(SIG_PATH, SCALE)
    fg = upscale_foreground(SIG_PATH, SCALE)
    print(f"  Foreground (upscaled): {fg.size}")

    # Compute the bounding box of the placed element for noise localisation.
    sig_box = (PLACE_X, PLACE_Y, PLACE_X + fg.width, PLACE_Y + fg.height)
    print(f"  Placing at: ({PLACE_X}, {PLACE_Y}), box={sig_box}")

    print("Compositing...")
    composited = composite_onto_page(page, fg, alpha, PLACE_X, PLACE_Y)

    # Save intermediate (pre-noise) for comparison.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    intermediate_path = OUT_DIR / "test_firma_pre_noise.png"
    composited.save(intermediate_path)
    print(f"  Intermediate (pre-noise): {intermediate_path}")

    print("Applying scanner noise...")
    noisy = scanner_effect(composited, box=sig_box, sigma=NOISE_SIGMA)

    print(f"Applying JPEG bake (Q={JPEG_QUALITY}, subsampling=2)...")
    final = jpeg_bake(noisy, quality=JPEG_QUALITY)

    # Save final image.
    final_path = OUT_DIR / "test_firma_final.jpg"
    final.save(final_path, quality=JPEG_QUALITY, subsampling=2, dpi=(TARGET_DPI, TARGET_DPI))
    print(f"  Final JPEG: {final_path}")

    # Also save as PNG for lossless inspection.
    png_path = OUT_DIR / "test_firma_final.png"
    final.save(png_path, dpi=(TARGET_DPI, TARGET_DPI))
    print(f"  Final PNG:  {png_path}")

    # Generate a comparison crop of the signature area.
    crop_box = (
        max(0, PLACE_X - 100),
        max(0, PLACE_Y - 20),
        min(page.width, PLACE_X + fg.width + 100),
        min(page.height, PLACE_Y + fg.height + 20),
    )
    
    # Before/after comparison crop.
    before_crop = page.crop(crop_box).convert("RGB")
    after_crop  = final.crop(crop_box).convert("RGB")
    comparison = Image.new("RGB", (before_crop.width * 2, before_crop.height))
    comparison.paste(before_crop, (0, 0))
    comparison.paste(after_crop, (before_crop.width, 0))
    
    comp_path = OUT_DIR / "test_firma_comparison.png"
    comparison.save(comp_path)
    print(f"  Comparison (before|after): {comp_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
