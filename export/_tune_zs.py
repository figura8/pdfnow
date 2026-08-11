"""Skeleton thinning at 300 DPI via skimage — continuous skeleton, no gaps.

1. Build alpha, upscale to 300 DPI, binarise
2. skimage.morphology.skeletonize → fully connected 1-px skeleton
3. Dilate by 0.7-2.2 px to match measured half-width (1.4 px)
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from skimage.morphology import skeletonize

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma3.png")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 0.35  # firma3.png has no DPI; scale to ~750px wide at 300 DPI
PLACE_X, PLACE_Y = 952, 2342


def sample_ink():
    page = Image.open(PAGE_PATH).convert("RGB")
    arr = np.asarray(page, dtype=np.float32)
    regions = [(475,3115,520,3140),(475,3090,530,3120),(2150,3110,2250,3145)]
    all_px = []
    for x0,y0,x1,y1 in regions:
        z = arr[y0:y1,x0:x1]
        mask = (z.max(axis=2) < 120) & (z.max(axis=2) > 15)
        if mask.sum() > 5: all_px.append(z[mask])
    return tuple(int(round(c)) for c in np.median(np.concatenate(all_px), axis=0))


def build_binary_300(sig_path, scale):
    """Build binary mask at 300 DPI from signature image."""
    im = Image.open(sig_path)
    if im.mode == "RGBA":
        # Check if alpha channel has variation (transparent background).
        alpha_ch = np.asarray(im)[:, :, 3]
        if alpha_ch.min() < 250:
            # Use alpha channel directly.
            alpha = alpha_ch.astype(np.float32) / 255.0
        else:
            # Alpha is all opaque — use luminance.
            src = np.asarray(im.convert("RGB")).mean(axis=2).astype(np.float32)
            bg = float(np.percentile(src, 95))
            ink = float(np.percentile(src, 2))
            alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)
    else:
        src = np.asarray(im.convert("L"), dtype=np.float32)
        bg = float(np.percentile(src, 95))
        ink = float(np.percentile(src, 2))
        alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)

    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))
    tw, th = round(im.width * scale), round(im.height * scale)
    alpha_img = alpha_img.resize((tw, th), Image.Resampling.LANCZOS)
    arr = np.asarray(alpha_img, dtype=np.float32) / 255.0
    binary = (arr > 0.5).astype(np.uint8)
    return binary



def dilate_alpha(skeleton, radius_px):
    """Dilate skeleton by radius_px (at 300 DPI) with soft edges."""
    if skeleton.sum() == 0:
        return np.zeros_like(skeleton, dtype=np.float32)

    import cv2
    kernel_size = max(3, int(round(radius_px * 2 + 1)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    iterations = max(1, int(round(radius_px)))
    dilated = cv2.dilate(skeleton.astype(np.uint8) * 255, kernel, iterations=iterations)

    # Distance transform for soft edges
    dist = cv2.distanceTransform(dilated, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    alpha = np.clip(dist / max(radius_px, 0.5), 0.0, 1.0)
    return alpha


def render(alpha_arr, blur, ink):
    img = Image.fromarray((alpha_arr * 255).astype(np.uint8), "L")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", img.size, (*ink, 255))
    fg.putalpha(img)
    white = Image.new("RGBA", img.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, fg).convert("RGB")


def composite_page(page, alpha_arr, x, y, blur, ink):
    img = Image.fromarray((alpha_arr * 255).astype(np.uint8), "L")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", img.size, (*ink, 255))
    fg.putalpha(img)
    layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
    layer.alpha_composite(fg, dest=(x, y))
    return Image.alpha_composite(page.convert("RGBA"), layer).convert("RGB")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ink = sample_ink()
    print(f"Ink: {ink}")

    print("Building binary mask @300DPI...")
    binary = build_binary_300(SIG_PATH, SCALE)
    print(f"  Binary: {binary.shape}, {binary.sum()} px")

    print("skimage skeletonize @300DPI...")
    skeleton = skeletonize(binary > 0).astype(np.uint8)
    n_skel = int(skeleton.sum())
    print(f"  Skeleton: {n_skel} px")

    # ── Variants ─────────────────────────────────────────────────────────
    variants = []
    for radius in [0.7, 1.0, 1.4, 1.8, 2.2]:
        alpha = dilate_alpha(skeleton, radius)
        nz = int((alpha > 0.01).sum())
        for blur in [0.2, 0.4]:
            label = f"r={radius} σ={blur}"
            rendered = render(alpha, blur, ink)
            variants.append((label, rendered))
            if blur == 0.2:
                print(f"  r={radius}: {nz} non-zero px")

    # ── Contact sheet ───────────────────────────────────────────────────
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
        col, row = i % COLS, i // COLS
        x0, y0 = col * tile_w + 2, row * tile_h + 2
        draw.text((x0, y0), label, fill=(40, 40, 40), font=font)
        sheet.paste(img, (x0, y0 + 18))
    cs_path = OUT_DIR / "tune_zs_contactsheet.png"
    sheet.save(cs_path)
    print(f"\nContact sheet: {cs_path}")

    # ── Context ──────────────────────────────────────────────────────────
    page = Image.open(PAGE_PATH).convert("RGB")
    margin = 80
    crop_box = (
        max(0, PLACE_X - margin), max(0, PLACE_Y - margin),
        min(page.width, PLACE_X + binary.shape[1] + margin),
        min(page.height, PLACE_Y + binary.shape[0] + margin),
    )
    page_crop = page.crop(crop_box)
    ref_crop = page.crop((420, 3060, 580, 3200))

    candidates = [
        ("r=0.7 σ=0.2", 0.7, 0.2),
        ("r=1.0 σ=0.2", 1.0, 0.2),
        ("r=1.4 σ=0.2", 1.4, 0.2),
        ("r=1.4 σ=0.4", 1.4, 0.4),
        ("r=1.8 σ=0.2", 1.8, 0.2),
        ("r=0.7 σ=0.4", 0.7, 0.4),
    ]
    ctx_panels = []
    for label, r, b in candidates:
        alpha = dilate_alpha(skeleton, r)
        comp = composite_page(page_crop, alpha, 0, 0, b, ink)
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
    ctx_path = OUT_DIR / "tune_zs_context.png"
    ctx_sheet.save(ctx_path)
    print(f"Context view: {ctx_path}")


if __name__ == "__main__":
    main()
