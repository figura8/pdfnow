"""Upscale-first thinning: no skeleton, no gaps.

Key insight: instead of skeletonizing at 96 DPI (which loses detail and
creates gaps), we upscale the continuous alpha mask to 300 DPI first,
then threshold at a high level to keep only the ink core.

At 300 DPI the stroke is ~9-15 px wide. Thresholding at alpha > 0.85
keeps only the darkest 1-3 px, matching the measured 1.4 px half-width.

Result: thin stroke with NO gaps, ALL detail preserved.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma.jpg")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 300 / 96
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


def build_alpha_upscaled(sig_path: Path, scale: float) -> np.ndarray:
    """Build continuous alpha mask, upscale to 300 DPI, return as float [0,1]."""
    im = Image.open(sig_path).convert("L")
    src = np.asarray(im, dtype=np.float32)
    bg = float(np.percentile(src, 95))
    ink = float(np.percentile(src, 2))
    alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)

    # Tiny blur at source to suppress JPEG artefacts
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))

    tw = round(im.width * scale)
    th = round(im.height * scale)
    alpha_img = alpha_img.resize((tw, th), Image.Resampling.LANCZOS)

    return np.asarray(alpha_img, dtype=np.float32) / 255.0


def threshold_alpha(alpha: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Remap alpha: below *lo* → 0, above *hi* → 1, linear in between."""
    result = np.clip((alpha - lo) / max(hi - lo, 0.01), 0.0, 1.0)
    return result


def render(alpha_arr: np.ndarray, blur: float, ink) -> Image.Image:
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

    print("Building upscaled alpha mask...")
    alpha_300 = build_alpha_upscaled(SIG_PATH, SCALE)
    print(f"  Alpha @300DPI: {alpha_300.shape}")

    # ── Variants: hard binary threshold at various levels ─────────────────
    # Higher threshold = thinner stroke (keep only the very core).
    variants = []
    for T in [0.70, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98]:
        # Hard threshold with tiny anti-aliasing window
        thresh = threshold_alpha(alpha_300, T, min(T + 0.02, 1.0))
        nz = int((thresh > 0.01).sum())
        for blur in [0.2, 0.4]:
            label = f"T={T} σ={blur}"
            rendered = render(thresh, blur, ink)
            variants.append((label, rendered))
            if blur == 0.2:
                print(f"  T={T}: {nz} non-zero px ({100*nz/thresh.size:.1f}%)")

    # ── Contact sheet ───────────────────────────────────────────────────
    COLS = 6
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

    cs_path = OUT_DIR / "tune_core_contactsheet.png"
    sheet.save(cs_path)
    print(f"\nContact sheet: {cs_path}")

    # ── Context view ────────────────────────────────────────────────────
    page = Image.open(PAGE_PATH).convert("RGB")
    margin = 80
    alpha_size = alpha_300.shape
    crop_box = (
        max(0, PLACE_X - margin), max(0, PLACE_Y - margin),
        min(page.width, PLACE_X + alpha_size[1] + margin),
        min(page.height, PLACE_Y + alpha_size[0] + margin),
    )
    page_crop = page.crop(crop_box)
    ref_crop = page.crop((420, 3060, 580, 3200))

    candidates = [
        ("T=.90 σ=0.4", 0.90, 0.92, 0.4),
        ("T=.93 σ=0.4", 0.93, 0.95, 0.4),
        ("T=.95 σ=0.4", 0.95, 0.97, 0.4),
        ("T=.95 σ=0.2", 0.95, 0.97, 0.2),
        ("T=.97 σ=0.4", 0.97, 0.99, 0.4),
        ("T=.85 σ=0.4", 0.85, 0.87, 0.4),
    ]

    ctx_panels = []
    for label, lo, hi, b in candidates:
        thresh = threshold_alpha(alpha_300, lo, hi)
        comp = composite_page(page_crop, thresh, 0, 0, b, ink)
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

    ctx_path = OUT_DIR / "tune_core_context.png"
    ctx_sheet.save(ctx_path)
    print(f"Context view: {ctx_path}")


if __name__ == "__main__":
    main()
