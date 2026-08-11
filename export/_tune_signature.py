"""Quick visual tuner: generate a contact sheet of signature variants.

Samples the ink colour from the existing signatures, then renders Francesco's
signature with different gamma/opacity/blur combos so you can pick the best
match by eye instead of relying on unreliable automatic metrics.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Paths ───────────────────────────────────────────────────────────────────
PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

TARGET_DPI = 300
SOURCE_DPI = 96
SCALE = TARGET_DPI / SOURCE_DPI

PLACE_X = 952
PLACE_Y = 2342

JPEG_QUALITY = 90


# ── Sample ink colour from narrow signature-only crops ─────────────────────
def sample_ink_color(page_path: Path) -> tuple[int, int, int]:
    """Sample core ink colour from existing signatures using tight crops."""
    page = Image.open(page_path).convert("RGB")
    arr = np.asarray(page, dtype=np.float32)

    # Very tight crops around just the signature strokes (avoid printed names).
    regions = [
        ("left stroke 1",  475, 3115, 520, 3140),
        ("left stroke 2",  475, 3090, 530, 3120),
        ("right stroke 1", 2150, 3110, 2250, 3145),
    ]

    all_pixels = []
    for name, x0, y0, x1, y1 in regions:
        zone = arr[y0:y1, x0:x1]
        gray = zone.max(axis=2)
        # Only the darkest ink core (threshold 120).
        ink_mask = (gray < 120) & (gray > 15)
        n_ink = int(ink_mask.sum())
        if n_ink > 5:
            all_pixels.append(zone[ink_mask])
            m = zone[ink_mask].mean(axis=0)
            print(f"  '{name}': {n_ink} px, mean=({m[0]:.0f},{m[1]:.0f},{m[2]:.0f})")

    combined = np.concatenate(all_pixels)
    median_color = np.median(combined, axis=0)
    print(f"  Target ink (median): ({median_color[0]:.0f}, {median_color[1]:.0f}, {median_color[2]:.0f})")
    return tuple(int(round(c)) for c in median_color)


# ── Build alpha mask from source signature ─────────────────────────────────
def build_alpha(sig_path: Path, scale: float, erode_px: int = 0) -> Image.Image:
    """Build continuous alpha mask, optionally eroding to thin the stroke.

    Erosion is applied at source resolution (before upscaling) so that
    *erode_px=1* removes roughly *scale* pixels at the target DPI.
    """
    im = Image.open(sig_path).convert("L")
    pixels = np.asarray(im, dtype=np.float32)
    bg = float(np.percentile(pixels, 95))
    ink = float(np.percentile(pixels, 2))
    alpha = np.clip((bg - pixels) / max(bg - ink, 1.0), 0.0, 1.0)
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))

    # ── Morphological erosion to thin the stroke ────────────────────────
    if erode_px > 0:
        arr = np.asarray(alpha_img)
        # Binarise at 50 % so erosion eats into the stroke edge.
        _, binary = cv2.threshold(arr, 127, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        eroded = cv2.erode(binary, kernel, iterations=erode_px)
        # Use eroded binary as mask on original continuous alpha:
        # keeps original alpha where eroded=1, zero elsewhere.
        alpha_eroded = np.asarray(eroded, dtype=np.float32) / 255.0
        alpha_orig = arr.astype(np.float32) / 255.0
        alpha_blend = alpha_orig * alpha_eroded
        alpha_img = Image.fromarray((alpha_blend * 255).astype(np.uint8), "L")

    tw = round(im.width * scale)
    th = round(im.height * scale)
    return alpha_img.resize((tw, th), Image.Resampling.LANCZOS)


# ── Render one variant ─────────────────────────────────────────────────────
def render_variant(
    alpha: Image.Image,
    gamma: float,
    opacity: float,
    blur: float,
    ink_color: tuple[int, int, int],
) -> Image.Image:
    """Render signature with given parameters on white background."""
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0.0, 1.0), gamma) * opacity
    arr = np.clip(arr, 0.0, 1.0)
    alpha_mod = Image.fromarray((arr * 255).astype(np.uint8), "L")
    if blur > 0:
        alpha_mod = alpha_mod.filter(ImageFilter.GaussianBlur(radius=blur))

    fg = Image.new("RGBA", alpha.size, (*ink_color, 255))
    fg.putalpha(alpha_mod)
    white_bg = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    return Image.alpha_composite(white_bg, fg).convert("RGB")


# ── Composite onto page crop ───────────────────────────────────────────────
def composite_crop(
    page_crop: Image.Image,
    alpha: Image.Image,
    gamma: float,
    opacity: float,
    blur: float,
    ink_color: tuple[int, int, int],
) -> Image.Image:
    """Composite signature onto a page crop (for context view)."""
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0.0, 1.0), gamma) * opacity
    arr = np.clip(arr, 0.0, 1.0)
    alpha_mod = Image.fromarray((arr * 255).astype(np.uint8), "L")
    if blur > 0:
        alpha_mod = alpha_mod.filter(ImageFilter.GaussianBlur(radius=blur))

    fg = Image.new("RGBA", alpha.size, (*ink_color, 255))
    fg.putalpha(alpha_mod)

    layer = Image.new("RGBA", page_crop.size, (0, 0, 0, 0))
    layer.alpha_composite(fg, dest=(0, 0))
    bg_rgba = page_crop.convert("RGBA")
    return Image.alpha_composite(bg_rgba, layer).convert("RGB")


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Sampling ink colour from existing signatures...")
    ink_color = sample_ink_color(PAGE_PATH)

    print("Building reference alpha mask (no erosion)...")
    alpha_ref = build_alpha(SIG_PATH, SCALE, erode_px=0)
    print(f"  Alpha size: {alpha_ref.size}")

    # Pre-build eroded variants
    eroded_alphas: dict[int, Image.Image] = {}
    for erode_px in [1, 2]:
        print(f"Building alpha with erode_px={erode_px}...")
        eroded_alphas[erode_px] = build_alpha(SIG_PATH, SCALE, erode_px=erode_px)

    # Crop the page around the placement area to show surrounding context
    # (including nearby existing signatures for visual comparison).
    page = Image.open(PAGE_PATH).convert("RGB")
    margin = 80
    crop_box = (
        max(0, PLACE_X - margin),
        max(0, PLACE_Y - margin),
        min(page.width, PLACE_X + alpha_ref.width + margin),
        min(page.height, PLACE_Y + alpha_ref.height + margin),
    )
    page_crop = page.crop(crop_box)

    # Also crop a region that includes the existing left signature for reference
    ref_box = (420, 3060, 580, 3200)
    ref_crop = page.crop(ref_box)

    # ── Generate variants ───────────────────────────────────────────────────
    # Primary knob: erosion (px at source DPI).
    # Secondary: gamma (fine-tunes remaining mid-tones).
    # Fixed: opacity=1.0, blur=0.7 (soften edges for scanner look).
    variants: list[tuple[str, Image.Image]] = []

    for erode_px in [0, 1, 2]:
        alpha = eroded_alphas.get(erode_px, alpha_ref)
        for gamma in [1.0, 1.5, 2.0, 2.5, 3.0]:
            for blur in [0.3, 0.7]:
                label = f"erode={erode_px} γ={gamma} σ={blur}"
                rendered = render_variant(alpha, gamma, 1.0, blur, ink_color)
                variants.append((label, rendered))

    print(f"Generated {len(variants)} variants.")

    # ── Build contact sheet ─────────────────────────────────────────────────
    COLS = 5
    tile_w = alpha.width + 4
    tile_h = alpha.height + 24
    rows = (len(variants) + COLS - 1) // COLS

    sheet = Image.new("RGB", (tile_w * COLS, tile_h * rows), (240, 240, 240))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("consola.ttf", 11)
    except OSError:
        font = ImageFont.load_default()

    for i, (label, img) in enumerate(variants):
        col = i % COLS
        row = i // COLS
        x0 = col * tile_w + 2
        y0 = row * tile_h + 2
        draw.text((x0, y0), label, fill=(40, 40, 40), font=font)
        sheet.paste(img, (x0, y0 + 18))

    sheet_path = OUT_DIR / "tune_signature_contactsheet.png"
    sheet.save(sheet_path)
    print(f"Contact sheet: {sheet_path}")

    # ── Context view: best candidates in-place on page crop ────────────────
    # Show a few promising combos placed on the actual page crop, with the
    # reference signature alongside for direct comparison.
    candidates = [
        ("erode=1 γ=1.0 σ=0.7", eroded_alphas[1], 1.0, 1.0, 0.7),
        ("erode=1 γ=1.5 σ=0.7", eroded_alphas[1], 1.5, 1.0, 0.7),
        ("erode=1 γ=2.0 σ=0.7", eroded_alphas[1], 2.0, 1.0, 0.7),
        ("erode=1 γ=2.5 σ=0.7", eroded_alphas[1], 2.5, 1.0, 0.7),
        ("erode=2 γ=1.0 σ=0.7", eroded_alphas[2], 1.0, 1.0, 0.7),
        ("erode=2 γ=1.5 σ=0.7", eroded_alphas[2], 1.5, 1.0, 0.7),
    ]

    context_panels = []
    for label, alpha_er, g, o, b in candidates:
        comp = composite_crop(page_crop, alpha_er, g, o, b, ink_color)
        # Label at top
        panel = Image.new("RGB", (comp.width, comp.height + 20), (255, 255, 255))
        panel.paste(comp, (0, 20))
        ImageDraw.Draw(panel).text((4, 3), label, fill=(40, 40, 40), font=font)
        context_panels.append(panel)

    # Also add reference signature crop
    ref_panel = Image.new("RGB", (ref_crop.width + 4, ref_crop.height + 20), (255, 255, 255))
    ref_panel.paste(ref_crop, (2, 20))
    ImageDraw.Draw(ref_panel).text((4, 3), "REFERENCE", fill=(40, 40, 40), font=font)

    # Build a 3-wide grid
    ctx_cols = 3
    ctx_rows = (len(context_panels) + 1 + ctx_cols - 1) // ctx_cols  # +1 for reference
    all_panels = context_panels + [ref_panel]
    max_w = max(p.width for p in all_panels)
    max_h = max(p.height for p in all_panels)

    ctx_sheet = Image.new("RGB", (max_w * ctx_cols, max_h * ctx_rows), (240, 240, 240))
    for i, panel in enumerate(all_panels):
        col = i % ctx_cols
        row = i // ctx_cols
        ctx_sheet.paste(panel, (col * max_w, row * max_h))

    ctx_path = OUT_DIR / "tune_signature_context.png"
    ctx_sheet.save(ctx_path)
    print(f"Context view: {ctx_path}")

    print("\nDone! Review the contact sheets and pick the best combo.")


if __name__ == "__main__":
    main()
