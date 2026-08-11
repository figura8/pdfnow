"""Comprehensive analysis of campione_tratto.png.

Extracts the four characteristics that define the pen stroke:
1. Ink tonalità & composizione (RGB distribution of ink)
2. Larghezza di base (stroke width at half-max)
3. Texture del tratto (high-frequency residual = paper grain + ink flow)
4. Difetti punta (voids, striations, ink pools)

Then uses these to render the signature with matching characteristics.
"""
from __future__ import annotations
import io, json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ── Paths ───────────────────────────────────────────────────────────────────
SAMPLE    = Path(r"c:\Users\maurizio\Documents\pdfnow\campione_tratto.png")
PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma3.png")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 0.35
PLACE_X, PLACE_Y = 952, 2342


# ═══════════════════════════════════════════════════════════════════════════
# 1. ANALISI DEL CAMPIONE
# ═══════════════════════════════════════════════════════════════════════════

def analyze_sample(sample_path: Path) -> dict:
    """Extract all four pen characteristics from the stroke sample."""
    im_rgb = Image.open(sample_path).convert("RGB")
    im_gray = np.asarray(im_rgb.convert("L"), dtype=np.float32)
    arr_rgb = np.asarray(im_rgb, dtype=np.float32)
    h, w = im_gray.shape

    # ── 1a. Tonalità inchiostro ─────────────────────────────────────────
    # Find ink pixels (darker than paper background).
    paper = float(np.percentile(im_gray, 95))
    ink_mask = im_gray < (paper - 15)  # at least 15 levels darker than paper
    ink_pixels_rgb = arr_rgb[ink_mask]
    n_ink = len(ink_pixels_rgb)

    ink_mean = ink_pixels_rgb.mean(axis=0) if n_ink > 0 else np.array([0,0,0])
    ink_median = np.median(ink_pixels_rgb, axis=0) if n_ink > 0 else np.array([0,0,0])
    ink_std = ink_pixels_rgb.std(axis=0) if n_ink > 0 else np.array([0,0,0])

    # Get the ink colour distribution in RGB space
    ink_p5 = np.percentile(ink_pixels_rgb, 5, axis=0) if n_ink > 0 else np.array([0,0,0])
    ink_p95 = np.percentile(ink_pixels_rgb, 95, axis=0) if n_ink > 0 else np.array([0,0,0])

    print(f"\n── Tonalità inchiostro ──")
    print(f"  Paper level: {paper:.0f}")
    print(f"  Ink pixels: {n_ink}")
    print(f"  Ink mean RGB:   ({ink_mean[0]:.0f}, {ink_mean[1]:.0f}, {ink_mean[2]:.0f})")
    print(f"  Ink median RGB: ({ink_median[0]:.0f}, {ink_median[1]:.0f}, {ink_median[2]:.0f})")
    print(f"  Ink std RGB:    ({ink_std[0]:.1f}, {ink_std[1]:.1f}, {ink_std[2]:.1f})")
    print(f"  Ink range: [{ink_p5[0]:.0f}-{ink_p95[0]:.0f}, ...]")

    # ── 1b. Larghezza di base ───────────────────────────────────────────
    # Find individual stroke segments and measure their width.
    dark = np.clip(paper - im_gray, 0, 255)
    binary = (dark > 15).astype(np.uint8)
    from scipy.ndimage import label
    labeled, n_labels = label(binary)

    stroke_widths = []
    for lbl in range(1, min(n_labels + 1, 80)):
        mask = (labeled == lbl)
        if mask.sum() < 50:
            continue
        ys, xs = np.where(mask)
        frag_w, frag_h = xs.ptp(), ys.ptp()
        if frag_w > 100 or frag_h > 100:
            continue

        # For horizontal-ish segments, measure vertical cross-section width.
        if frag_w >= frag_h:
            mid_y = ys[len(ys)//2]
            row = dark[mid_y, xs.min():xs.max()+1]
            above_half = (row > row.max() * 0.5).sum()
            stroke_widths.append(above_half)
        else:
            mid_x = xs[len(xs)//2]
            col = dark[ys.min():ys.max()+1, mid_x]
            above_half = (col > col.max() * 0.5).sum()
            stroke_widths.append(above_half)

    base_width = float(np.median(stroke_widths)) if stroke_widths else 0
    print(f"\n── Larghezza di base ──")
    print(f"  Segments measured: {len(stroke_widths)}")
    print(f"  Median width (FWHM): {base_width:.1f} px at sample res")

    # ── 1c. Texture del tratto ──────────────────────────────────────────
    # High-frequency residual after Gaussian blur = paper grain + ink flow.
    blurred = cv2.GaussianBlur(im_gray, (0, 0), sigmaX=3.0)
    texture = im_gray - blurred
    # Only texture ON the ink (not paper)
    texture_ink = texture[ink_mask]
    tex_std = float(np.std(texture_ink)) if n_ink > 0 else 0

    # Normalize texture for transfer
    texture_norm = texture / max(tex_std * 3, 1.0)

    print(f"\n── Texture del tratto ──")
    print(f"  Texture σ (on ink): {tex_std:.2f}")
    print(f"  Texture saved as normalized field")

    # ── 1d. Difetti della punta ─────────────────────────────────────────
    # Voids: ink pixels that are surrounded by darker ink (local minima).
    # Striations: linear patterns along the stroke direction.
    # Ink pools: local maxima of darkness.

    # Detect voids (small light spots within dark strokes).
    # A void pixel is: part of stroke, but lighter than local median.
    local_median = cv2.medianBlur(im_gray.astype(np.uint8), 5).astype(np.float32)
    void_candidates = ink_mask & (im_gray > local_median + 8)
    n_voids = int(void_candidates.sum())

    # Detect ink pools (very dark concentrated spots).
    pool_candidates = ink_mask & (im_gray < np.percentile(ink_pixels_rgb.mean(axis=1) if n_ink > 0 else [0], 10))
    n_pools = int(pool_candidates.sum()) if n_ink > 0 else 0

    # Detect striations: linear features using oriented gradients.
    # Use structure tensor to find line-like patterns.
    gx = cv2.Sobel(im_gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(im_gray, cv2.CV_32F, 0, 1, ksize=3)
    # Coherence: how line-like the local structure is.
    gxx = cv2.GaussianBlur(gx*gx, (0,0), 2.0)
    gyy = cv2.GaussianBlur(gy*gy, (0,0), 2.0)
    gxy = cv2.GaussianBlur(gx*gy, (0,0), 2.0)
    coherence = np.sqrt((gxx - gyy)**2 + 4*gxy**2) / (gxx + gyy + 1e-6)
    striation_mask = (coherence > 0.5) & ink_mask
    n_striations = int(striation_mask.sum())

    print(f"\n── Difetti della punta ──")
    print(f"  Voids (local light spots): {n_voids} px")
    print(f"  Ink pools (concentrations): {n_pools} px")
    print(f"  Striations (linear texture): {n_striations} px")

    return {
        "ink_rgb": {
            "mean": [round(v, 1) for v in ink_mean.tolist()],
            "median": [round(v, 1) for v in ink_median.tolist()],
            "std": [round(v, 1) for v in ink_std.tolist()],
            "p5": [round(v, 1) for v in ink_p5.tolist()],
            "p95": [round(v, 1) for v in ink_p95.tolist()],
        },
        "base_width_px": base_width,
        "texture_sigma": tex_std,
        "defects": {
            "voids_px": n_voids,
            "pools_px": n_pools,
            "striations_px": n_striations,
        },
        # For texture transfer
        "texture_field": texture_norm,
        "ink_mask": ink_mask,
        "paper_level": paper,
        "sample_size": [w, h],
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. RENDERING CON CARATTERISTICHE DEL CAMPIONE
# ═══════════════════════════════════════════════════════════════════════════

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


def texture_transfer(alpha: np.ndarray, analysis: dict, seed: int = 13) -> np.ndarray:
    """Transfer the texture characteristics from the sample onto our alpha.

    Uses the normalized texture field from the sample, tiled/scaled to fit.
    """
    tex_field = analysis["texture_field"]
    tex_sigma = analysis["texture_sigma"]
    h, w = alpha.shape
    th, tw = tex_field.shape

    # Tile the texture field to cover our alpha
    tile_h = (h + th - 1) // th
    tile_w = (w + tw - 1) // tw
    tiled = np.tile(tex_field, (tile_h, tile_w))[:h, :w]

    # Scale texture intensity to match sample
    tiled = tiled * (tex_sigma / max(np.std(tiled), 0.1))

    # Only apply texture where there's ink
    ink_zone = alpha > 0.02
    result = alpha.copy()
    result[ink_zone] = np.clip(alpha[ink_zone] + tiled[ink_zone] * 0.08, 0, 1)

    return result


def add_pen_defects(alpha: np.ndarray, analysis: dict, seed: int = 13) -> np.ndarray:
    """Add simulated pen defects (voids, pools) matching sample statistics."""
    rng = np.random.default_rng(seed)
    h, w = alpha.shape
    ink_zone = alpha > 0.02
    n_ink = int(ink_zone.sum())

    if n_ink == 0:
        return alpha

    defects = analysis["defects"]

    # Void density from sample
    void_density = defects["voids_px"] / max(analysis["ink_mask"].sum(), 1)
    n_voids_target = int(n_ink * void_density)

    # Pool density from sample
    pool_density = defects["pools_px"] / max(analysis["ink_mask"].sum(), 1)
    n_pools_target = int(n_ink * pool_density)

    result = alpha.copy()

    # Add voids (small random reductions in alpha)
    if n_voids_target > 0:
        void_positions_h = rng.integers(0, h, n_voids_target)
        void_positions_w = rng.integers(0, w, n_voids_target)
        # Only place voids where there's actual ink
        for y, x in zip(void_positions_h, void_positions_w):
            if alpha[y, x] > 0.3:
                result[y, x] *= rng.uniform(0.5, 0.85)

    # Add ink pools (small alpha increases)
    if n_pools_target > 0:
        pool_positions_h = rng.integers(0, h, n_pools_target)
        pool_positions_w = rng.integers(0, w, n_pools_target)
        for y, x in zip(pool_positions_h, pool_positions_w):
            if alpha[y, x] > 0.2:
                result[y, x] = min(1.0, alpha[y, x] * rng.uniform(1.05, 1.20))

    return result


def composite_page(page, alpha_arr, x, y, blur, ink_rgb):
    img = Image.fromarray((alpha_arr * 255).astype(np.uint8), "L")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", img.size, (*ink_rgb, 255))
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


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Analyze sample ──────────────────────────────────────────────────
    print("=" * 60)
    print("ANALYZING campione_tratto.png")
    print("=" * 60)
    analysis = analyze_sample(SAMPLE)

    # Save analysis
    analysis_serializable = {
        k: v for k, v in analysis.items()
        if k not in ("texture_field", "ink_mask")
    }
    with open(OUT_DIR / "campione_analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis_serializable, f, indent=2)

    # Use the median ink colour from the sample directly
    ink_rgb = tuple(int(round(c)) for c in analysis["ink_rgb"]["median"])

    # ── Build signature alpha ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RENDERING SIGNATURE")
    print("=" * 60)
    print(f"Using ink colour from sample: {ink_rgb}")

    page = Image.open(PAGE_PATH).convert("RGB")
    alpha = build_alpha(SIG_PATH, SCALE)
    print(f"Alpha: {alpha.shape[1]}x{alpha.shape[0]}")

    # Apply power curve for thinning
    for power, blur, label in [
        (2.8, 0.0, "sample_p28"),
        (3.0, 0.0, "sample_p30"),
        (3.2, 0.0, "sample_p32"),
        (3.0, 0.1, "sample_p30b"),
    ]:
        print(f"\nPower={power} blur={blur} ({label})")

        thinned = np.power(np.clip(alpha, 0, 1), power)

        # Transfer texture from sample
        thinned = texture_transfer(thinned, analysis)

        # Add pen defects matching sample
        thinned = add_pen_defects(thinned, analysis)

        nz = int((thinned > 0.01).sum())
        print(f"  non-zero: {nz}")

        comp = composite_page(page, thinned, PLACE_X, PLACE_Y, blur, ink_rgb)
        box = (PLACE_X, PLACE_Y, PLACE_X + thinned.shape[1], PLACE_Y + thinned.shape[0])
        noisy = scanner_noise(comp, box)
        final = jpeg_bake(noisy)
        final.save(OUT_DIR / f"firma3_{label}.png", dpi=(300, 300))

    print(f"\nDone! Files in {OUT_DIR}/")


if __name__ == "__main__":
    main()
