"""Distance-transform thinning: a completely different approach from erosion.

Instead of eating away at the edge (which distorts shape), we:
1. Compute the distance transform (distance of each stroke pixel to nearest edge)
2. Threshold: keep only pixels whose distance > D  (D = how much to thin)
3. Remap remaining distances to continuous alpha for smooth edges
4. This preserves the medial axis — the "spine" of the signature

Result: a uniform thinning that respects the original stroke topology.
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
SCALE = TARGET_DPI / SOURCE_DPI  # 3.125

PLACE_X = 952
PLACE_Y = 2342

INK_COLOR = (77, 77, 77)


# ── Sample ink colour ──────────────────────────────────────────────────────
def sample_ink_color(page_path: Path) -> tuple[int, int, int]:
    page = Image.open(page_path).convert("RGB")
    arr = np.asarray(page, dtype=np.float32)
    regions = [
        ("left 1",  475, 3115, 520, 3140),
        ("left 2",  475, 3090, 530, 3120),
        ("right",  2150, 3110, 2250, 3145),
    ]
    all_pixels = []
    for _, x0, y0, x1, y1 in regions:
        zone = arr[y0:y1, x0:x1]
        gray = zone.max(axis=2)
        ink_mask = (gray < 120) & (gray > 15)
        if ink_mask.sum() > 5:
            all_pixels.append(zone[ink_mask])
    combined = np.concatenate(all_pixels)
    median_color = np.median(combined, axis=0)
    return tuple(int(round(c)) for c in median_color)


# ── Distance-transform thinning ────────────────────────────────────────────
def build_thinned_alpha(
    sig_path: Path,
    scale: float,
    distance_threshold: float,
) -> Image.Image:
    """Build alpha mask thinned via distance transform.

    *distance_threshold*: keep only pixels whose distance from the stroke
    edge is greater than this value (in source-resolution pixels).
    Larger values = thinner stroke.

    Returns continuous alpha (0-1), already upscaled to target DPI.
    """
    im = Image.open(sig_path).convert("L")
    src_arr = np.asarray(im, dtype=np.float32)

    # Continuous alpha from luminance (same as before).
    bg = float(np.percentile(src_arr, 95))
    ink = float(np.percentile(src_arr, 2))
    alpha = np.clip((bg - src_arr) / max(bg - ink, 1.0), 0.0, 1.0)

    # Binarise for distance transform.
    binary = (alpha > 0.5).astype(np.uint8) * 255

    if binary.sum() < 10:
        # No stroke found — return empty alpha.
        tw = round(im.width * scale)
        th = round(im.height * scale)
        return Image.new("L", (tw, th), 0)

    # Distance transform: for each white pixel, distance to nearest black pixel.
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)

    # Thin: zero out pixels within *distance_threshold* of the edge.
    thinned_binary = (dist > distance_threshold).astype(np.uint8) * 255

    if thinned_binary.sum() < 5:
        # Too aggressive — fall back to a minimal skeleton.
        from skimage.morphology import skeletonize
        skel = skeletonize(binary > 0)
        thinned_binary = skel.astype(np.uint8) * 255

    # Build continuous alpha: remap remaining distance values to [0, 1].
    # Pixels at the threshold edge → alpha ≈ 0 (soft fade).
    # Pixels at the core (max distance) → alpha ≈ 1.
    remaining_dist = dist.copy()
    remaining_dist[thinned_binary == 0] = 0
    max_d = remaining_dist.max()
    if max_d > 0:
        # Remap: distance_threshold+0.5 → 0.05, max_d → 1.0
        # This gives a soft edge at the threshold boundary.
        fade_start = distance_threshold + 0.3
        fade_range = max(max_d - fade_start, 0.3)
        result = np.clip((remaining_dist - fade_start) / fade_range, 0.0, 1.0)
    else:
        result = thinned_binary.astype(np.float32) / 255.0

    alpha_img = Image.fromarray((result * 255).astype(np.uint8), "L")

    # Upscale to target DPI.
    tw = round(im.width * scale)
    th = round(im.height * scale)
    return alpha_img.resize((tw, th), Image.Resampling.LANCZOS)


# ── Render one variant ─────────────────────────────────────────────────────
def render_variant(
    alpha: Image.Image,
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
    white_bg = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    return Image.alpha_composite(white_bg, fg).convert("RGB")


# ── Composite onto page crop ───────────────────────────────────────────────
def composite_crop(
    page_crop: Image.Image,
    alpha: Image.Image,
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

    layer = Image.new("RGBA", page_crop.size, (0, 0, 0, 0))
    layer.alpha_composite(fg, dest=(0, 0))
    bg_rgba = page_crop.convert("RGBA")
    return Image.alpha_composite(bg_rgba, layer).convert("RGB")


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Sampling ink colour...")
    ink_color = sample_ink_color(PAGE_PATH)
    print(f"  Ink: {ink_color}")

    print("\nBuilding distance-transform variants...")
    variants: list[tuple[str, Image.Image]] = []

    # distance_threshold: how many source pixels to peel from the edge.
    # At source 96 DPI, each pixel ≈ 3 target pixels at 300 DPI.
    for dt in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
        print(f"  dt={dt}...")
        alpha = build_thinned_alpha(SIG_PATH, SCALE, distance_threshold=dt)
        for gamma in [1.0, 1.3]:
            for blur in [0.5, 0.7]:
                label = f"dt={dt} γ={gamma} σ={blur}"
                rendered = render_variant(alpha, gamma, blur, ink_color)
                variants.append((label, rendered))

    print(f"\nGenerated {len(variants)} variants.")

    # ── Contact sheet ───────────────────────────────────────────────────────
    COLS = 4
    tile_w = variants[0][1].width + 4
    tile_h = variants[0][1].height + 24
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

    sheet_path = OUT_DIR / "tune_dt_contactsheet.png"
    sheet.save(sheet_path)
    print(f"Contact sheet: {sheet_path}")

    # ── Context view ────────────────────────────────────────────────────────
    page = Image.open(PAGE_PATH).convert("RGB")
    margin = 80
    alpha_ref = build_thinned_alpha(SIG_PATH, SCALE, distance_threshold=0.0)
    crop_box = (
        max(0, PLACE_X - margin),
        max(0, PLACE_Y - margin),
        min(page.width, PLACE_X + alpha_ref.width + margin),
        min(page.height, PLACE_Y + alpha_ref.height + margin),
    )
    page_crop = page.crop(crop_box)
    ref_crop_box = (420, 3060, 580, 3200)
    ref_crop = page.crop(ref_crop_box)

    # Best candidates at different distance thresholds
    candidates = [
        ("dt=1.5 γ=1.0 σ=0.7", 1.5, 1.0, 0.7),
        ("dt=2.0 γ=1.0 σ=0.7", 2.0, 1.0, 0.7),
        ("dt=2.5 γ=1.0 σ=0.7", 2.5, 1.0, 0.7),
        ("dt=2.0 γ=1.3 σ=0.7", 2.0, 1.3, 0.7),
        ("dt=2.5 γ=1.3 σ=0.7", 2.5, 1.3, 0.7),
        ("dt=3.0 γ=1.0 σ=0.7", 3.0, 1.0, 0.7),
    ]

    context_panels = []
    for label, dt, g, b in candidates:
        alpha = build_thinned_alpha(SIG_PATH, SCALE, distance_threshold=dt)
        comp = composite_crop(page_crop, alpha, g, b, ink_color)
        panel = Image.new("RGB", (comp.width, comp.height + 20), (255, 255, 255))
        panel.paste(comp, (0, 20))
        ImageDraw.Draw(panel).text((4, 3), label, fill=(40, 40, 40), font=font)
        context_panels.append(panel)

    ref_panel = Image.new("RGB", (ref_crop.width + 4, ref_crop.height + 20), (255, 255, 255))
    ref_panel.paste(ref_crop, (2, 20))
    ImageDraw.Draw(ref_panel).text((4, 3), "REFERENCE", fill=(40, 40, 40), font=font)

    all_panels = context_panels + [ref_panel]
    ctx_cols = 3
    ctx_rows = (len(all_panels) + ctx_cols - 1) // ctx_cols
    max_w = max(p.width for p in all_panels)
    max_h = max(p.height for p in all_panels)

    ctx_sheet = Image.new("RGB", (max_w * ctx_cols, max_h * ctx_rows), (240, 240, 240))
    for i, panel in enumerate(all_panels):
        col = i % ctx_cols
        row = i // ctx_cols
        ctx_sheet.paste(panel, (col * max_w, row * max_h))

    ctx_path = OUT_DIR / "tune_dt_context.png"
    ctx_sheet.save(ctx_path)
    print(f"Context view: {ctx_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
