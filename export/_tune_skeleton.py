"""Skeletonize + measure + re-render: the nuclear option.

1. Measure stroke half-width of existing signatures (distance transform).
2. Extract the medial axis (skeleton) from firma.jpg.
3. Dilate the skeleton to match the measured width.
4. Render with sampled ink colour.

This completely replaces the original stroke — we keep only the shape
(centerline) and redraw it at the correct thickness.
"""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 300 / 96
PLACE_X, PLACE_Y = 952, 2342


# ── 1. Measure existing signature stroke width ─────────────────────────────
def measure_stroke_halfwidth(page_path: Path) -> float:
    """Return the median half-width (radius) of existing signature strokes, in
    source-resolution-equivalent pixels (i.e. at 96 DPI before upscale)."""
    page = Image.open(page_path).convert("L")
    arr = np.asarray(page, dtype=np.float32)

    # Tight crops around just the signature strokes.
    regions = [
        (475, 3115, 520, 3140),
        (475, 3090, 530, 3120),
        (2150, 3110, 2250, 3145),
    ]

    all_halfwidths = []
    for x0, y0, x1, y1 in regions:
        crop = arr[y0:y1, x0:x1]
        # Binarise: ink pixels < 180 (darker than paper).
        binary = (crop < 180).astype(np.uint8) * 255
        if binary.sum() < 5:
            continue
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        # Half-width at each stroke pixel = distance to nearest edge.
        stroke_pixels = dist[binary > 0]
        all_halfwidths.extend(stroke_pixels.tolist())

    if not all_halfwidths:
        return 0.8  # fallback

    # At 300 DPI. Convert to source (96 DPI) equivalent.
    median_300dpi = float(np.median(all_halfwidths))
    median_src = median_300dpi / SCALE
    print(f"  Measured half-width: {median_300dpi:.2f} px @300DPI = {median_src:.2f} px @96DPI")
    return median_src


# ── 2. Build skeleton (medial axis) from firma.jpg ─────────────────────────
def build_skeleton(sig_path: Path) -> np.ndarray:
    """Extract the medial axis of the signature as a binary mask at source res.

    Uses distance-transform local-maxima (no extra dependencies).
    Returns binary uint8 array (255 = skeleton).
    """
    im = Image.open(sig_path).convert("L")
    src = np.asarray(im, dtype=np.float32)

    # Alpha mask
    bg = float(np.percentile(src, 95))
    ink = float(np.percentile(src, 2))
    alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)

    # Binarise
    binary = (alpha > 0.5).astype(np.uint8) * 255
    if binary.sum() < 10:
        return binary

    # Distance transform
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)

    # Find local maxima (skeleton points) — vectorised.
    # A pixel is on the skeleton if its distance value >= all 8 neighbours.
    h, w = dist.shape
    padded = np.pad(dist, 1, mode='constant', constant_values=0)

    is_max = np.ones((h, w), dtype=bool)
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            if dy == 0 and dx == 0:
                continue
            is_max &= (dist >= padded[1+dy:1+dy+h, 1+dx:1+dx+w])

    skeleton = ((binary > 0) & is_max).astype(np.uint8) * 255

    n_skeleton = skeleton.sum() // 255
    print(f"  Skeleton pixels: {n_skeleton}")
    return skeleton


# ── 3. Dilate skeleton to target width ─────────────────────────────────────
def dilate_skeleton(skeleton: np.ndarray, radius_px: float) -> Image.Image:
    """Dilate the skeleton by *radius_px* (at source DPI) to get the desired
    stroke thickness. Returns a continuous alpha mask (0-1) at source res."""
    if skeleton.sum() == 0:
        return Image.new("L", skeleton.shape[::-1], 0)

    # Dilate binary skeleton
    kernel_size = max(3, int(round(radius_px * 2 + 1)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    iterations = max(1, int(round(radius_px)))
    dilated = cv2.dilate(skeleton, kernel, iterations=iterations)

    # Distance transform on dilated mask for soft edges
    dist_dilated = cv2.distanceTransform(dilated, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    # Remap: 0 → 0, radius → 1 (soft fade at the edge)
    alpha_soft = np.clip(dist_dilated / max(radius_px, 0.5), 0.0, 1.0)

    return Image.fromarray((alpha_soft * 255).astype(np.uint8), "L")


# ── 4. Upscale + render ────────────────────────────────────────────────────
def upscale_alpha(alpha_src: Image.Image, scale: float) -> Image.Image:
    tw = round(alpha_src.width * scale)
    th = round(alpha_src.height * scale)
    return alpha_src.resize((tw, th), Image.Resampling.LANCZOS)


def render(alpha: Image.Image, gamma: float, blur: float, ink) -> Image.Image:
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0, 1), gamma)
    alpha_mod = Image.fromarray((arr * 255).astype(np.uint8), "L")
    if blur > 0:
        alpha_mod = alpha_mod.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", alpha.size, (*ink, 255))
    fg.putalpha(alpha_mod)
    white = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, fg).convert("RGB")


def composite_page(page, alpha, x, y, gamma, blur, ink):
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


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Sample ink colour
    page_rgb = Image.open(PAGE_PATH).convert("RGB")
    arr_rgb = np.asarray(page_rgb, dtype=np.float32)
    regions = [(475,3115,520,3140),(475,3090,530,3120),(2150,3110,2250,3145)]
    all_px = []
    for x0,y0,x1,y1 in regions:
        z = arr_rgb[y0:y1,x0:x1]
        mask = (z.max(axis=2) < 120) & (z.max(axis=2) > 15)
        if mask.sum() > 5: all_px.append(z[mask])
    ink_color = tuple(int(round(c)) for c in np.median(np.concatenate(all_px), axis=0))
    print(f"Ink colour: {ink_color}")

    # Measure target stroke width
    print("\nMeasuring existing signature stroke width...")
    target_halfwidth = measure_stroke_halfwidth(PAGE_PATH)

    # Build skeleton
    print("\nBuilding skeleton from firma.jpg...")
    skeleton = build_skeleton(SIG_PATH)

    # ── Generate variants ───────────────────────────────────────────────────
    print("\nGenerating variants...")
    variants: list[tuple[str, Image.Image]] = []

    # Try different radii around the measured one
    for radius_factor in [0.5, 0.7, 1.0, 1.3, 1.5]:
        radius = target_halfwidth * radius_factor
        print(f"  radius={radius:.2f} (×{radius_factor})")
        alpha_src = dilate_skeleton(skeleton, radius)
        alpha = upscale_alpha(alpha_src, SCALE)

        for gamma in [1.0, 1.2]:
            for blur in [0.5, 0.7]:
                label = f"r={radius:.1f} γ={gamma} σ={blur}"
                rendered = render(alpha, gamma, blur, ink_color)
                variants.append((label, rendered))

    print(f"\nGenerated {len(variants)} variants.")

    # ── Contact sheet ───────────────────────────────────────────────────────
    COLS = 5
    tile_w = variants[0][1].width + 4
    tile_h = variants[0][1].height + 24
    rows = (len(variants) + COLS - 1) // COLS

    sheet = Image.new("RGB", (tile_w * COLS, tile_h * rows), (240, 240, 240))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("consola.ttf", 10)
    except OSError:
        font = ImageFont.load_default()

    for i, (label, img) in enumerate(variants):
        col = i % COLS; row = i // COLS
        x0, y0 = col * tile_w + 2, row * tile_h + 2
        draw.text((x0, y0), label, fill=(40, 40, 40), font=font)
        sheet.paste(img, (x0, y0 + 18))

    sheet_path = OUT_DIR / "tune_skeleton_contactsheet.png"
    sheet.save(sheet_path)
    print(f"Contact sheet: {sheet_path}")

    # ── Context view ────────────────────────────────────────────────────────
    alpha_ref = dilate_skeleton(skeleton, target_halfwidth * 1.0)
    alpha_ref = upscale_alpha(alpha_ref, SCALE)
    margin = 80
    crop_box = (
        max(0, PLACE_X - margin), max(0, PLACE_Y - margin),
        min(page_rgb.width, PLACE_X + alpha_ref.width + margin),
        min(page_rgb.height, PLACE_Y + alpha_ref.height + margin),
    )
    page_crop = page_rgb.crop(crop_box)
    ref_crop = page_rgb.crop((420, 3060, 580, 3200))

    candidates = [
        ("r=×0.5 γ=1.0 σ=0.7", 0.5, 1.0, 0.7),
        ("r=×0.7 γ=1.0 σ=0.7", 0.7, 1.0, 0.7),
        ("r=×1.0 γ=1.0 σ=0.7", 1.0, 1.0, 0.7),
        ("r=×1.0 γ=1.2 σ=0.7", 1.0, 1.2, 0.7),
        ("r=×1.3 γ=1.0 σ=0.7", 1.3, 1.0, 0.7),
        ("r=×1.5 γ=1.0 σ=0.7", 1.5, 1.0, 0.7),
    ]

    ctx_panels = []
    for label, rf, g, b in candidates:
        a_src = dilate_skeleton(skeleton, target_halfwidth * rf)
        a = upscale_alpha(a_src, SCALE)
        comp = composite_page(page_crop, a, 0, 0, g, b, ink_color)
        panel = Image.new("RGB", (comp.width, comp.height + 20), (255, 255, 255))
        panel.paste(comp, (0, 20))
        ImageDraw.Draw(panel).text((4, 3), label, fill=(40, 40, 40), font=font)
        ctx_panels.append(panel)

    ref_panel = Image.new("RGB", (ref_crop.width+4, ref_crop.height+20), (255,255,255))
    ref_panel.paste(ref_crop, (2, 20))
    ImageDraw.Draw(ref_panel).text((4, 3), "REFERENCE", fill=(40,40,40), font=font)

    all_panels = ctx_panels + [ref_panel]
    COLS_C = 3
    rows_c = (len(all_panels) + COLS_C - 1) // COLS_C
    mw = max(p.width for p in all_panels)
    mh = max(p.height for p in all_panels)
    ctx_sheet = Image.new("RGB", (mw * COLS_C, mh * rows_c), (240,240,240))
    for i, p in enumerate(all_panels):
        ctx_sheet.paste(p, ((i % COLS_C) * mw, (i // COLS_C) * mh))

    ctx_path = OUT_DIR / "tune_skeleton_context.png"
    ctx_sheet.save(ctx_path)
    print(f"Context view: {ctx_path}")

    print(f"\nDone! Measured half-width: {target_halfwidth:.2f} src px")


if __name__ == "__main__":
    main()
