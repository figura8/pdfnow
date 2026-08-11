"""
Calibration script: tune compositing parameters to match existing stroke elements.

1. Samples metrics (darkness, edge energy, coverage) from existing elements on the page
2. Tests multiple gamma/opacity/blur combinations on the inserted element
3. Picks the best match and generates the final output.
"""
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

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
NOISE_SIGMA  = 1.0


# ── Metrics (same as benchmark) ─────────────────────────────────────────────
def compute_metrics(image: Image.Image) -> dict[str, float]:
    """Extract darkness, coverage, and edge energy from a stroke image."""
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    darkness = 255 - gray
    active = darkness > 8
    if not active.any():
        return {"mean_darkness_active": 0.0, "dark_pixel_fraction": 0.0, "edge_energy": 0.0}
    import cv2
    edges = cv2.Laplacian(gray, cv2.CV_32F)
    return {
        "mean_darkness_active": round(float(darkness[active].mean()), 3),
        "dark_pixel_fraction": round(float((darkness > 35).mean()), 5),
        "edge_energy": round(float(np.mean(np.abs(edges))), 4),
    }


def distance(ref: dict, test: dict) -> float:
    """Normalised sum of absolute differences."""
    return sum(
        abs(test[k] - ref[k]) / max(abs(ref[k]), 1e-6)
        for k in ("mean_darkness_active", "dark_pixel_fraction", "edge_energy")
    )


# ── Sample reference metrics from existing strokes on the page ──────────────
def sample_reference_metrics(page_path: Path) -> dict[str, float]:
    """Extract metrics from the two existing stroke patterns on the page."""
    page = Image.open(page_path).convert("L")
    arr = np.asarray(page, dtype=np.float32)

    # Existing stroke regions (from earlier analysis)
    regions = [
        ("left",  460, 3095, 540, 3165),
        ("right", 2140, 3095, 2260, 3165),
    ]

    all_metrics = []
    for name, x0, y0, x1, y1 in regions:
        crop = page.crop((x0, y0, x1, y1))
        m = compute_metrics(crop)
        print(f"  Reference '{name}': {m}")
        all_metrics.append(m)

    # Average the two references
    avg = {}
    for k in all_metrics[0]:
        avg[k] = round(sum(m[k] for m in all_metrics) / len(all_metrics), 5)
    print(f"  Reference (averaged): {avg}")
    return avg


# ── Sample ink colour from existing signatures ──────────────────────────────
def sample_ink_color(page_path: Path) -> tuple[int, int, int]:
    """Sample the ink colour (RGB) from the existing signatures on the page.

    Uses median of ink pixels across all reference signature regions so the
    inserted element matches the same pen colour.
    """
    page = Image.open(page_path).convert("RGB")
    arr = np.asarray(page, dtype=np.float32)

    regions = [
        ("left sig",  460, 3095, 540, 3165),
        ("right sig", 2140, 3095, 2260, 3165),
    ]

    all_pixels = []
    for name, x0, y0, x1, y1 in regions:
        zone = arr[y0:y1, x0:x1]
        # Identify core ink pixels: substantially darker than paper (threshold 150
        # instead of 200 to exclude grey edge pixels that blend ink with paper).
        gray = zone.max(axis=2)
        ink_mask = (gray < 150) & (gray > 20)
        n_ink = int(ink_mask.sum())
        if n_ink > 10:
            all_pixels.append(zone[ink_mask])
            print(f"  '{name}': {n_ink} ink pixels, mean=({zone[ink_mask].mean(axis=0)[0]:.0f},{zone[ink_mask].mean(axis=0)[1]:.0f},{zone[ink_mask].mean(axis=0)[2]:.0f})")

    combined = np.concatenate(all_pixels)
    median_color = np.median(combined, axis=0)
    print(f"  Target ink colour (median): ({median_color[0]:.0f}, {median_color[1]:.0f}, {median_color[2]:.0f})")
    return tuple(int(round(c)) for c in median_color)


# ── Build alpha mask + upscale ──────────────────────────────────────────────
def build_alpha(sig_path: Path, scale: float) -> Image.Image:
    im = Image.open(sig_path).convert("L")
    pixels = np.asarray(im, dtype=np.float32)
    bg = float(np.percentile(pixels, 95))
    ink = float(np.percentile(pixels, 2))
    alpha = np.clip((bg - pixels) / max(bg - ink, 1.0), 0.0, 1.0)
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))
    tw = round(im.width * scale)
    th = round(im.height * scale)
    return alpha_img.resize((tw, th), Image.Resampling.LANCZOS)


def upscale_rgb(sig_path: Path, scale: float) -> Image.Image:
    """Upscale the signature RGB to target DPI via Lanczos.

    Kept for comparative testing; the calibrated pipeline uses ink_color
    from sample_ink_color() instead of the source image's own RGB.
    """
    im = Image.open(sig_path).convert("RGB")
    im = im.filter(ImageFilter.GaussianBlur(radius=0.15))
    tw = round(im.width * scale)
    th = round(im.height * scale)
    return im.resize((tw, th), Image.Resampling.LANCZOS)


# ── Render stroke with given parameters ─────────────────────────────────────
def render_stroke(
    alpha: Image.Image,
    gamma: float,
    opacity: float,
    blur: float,
    ink_color: tuple[int, int, int],
) -> Image.Image:
    """Apply gamma, opacity, blur to alpha, then tint with *ink_color* over white.

    The shape comes from the alpha mask (extracted from the source signature)
    while the RGB colour is forced to *ink_color* so it matches the existing
    pen strokes on the page.
    """
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0.0, 1.0), gamma) * opacity
    arr = np.clip(arr, 0.0, 1.0)
    alpha_mod = Image.fromarray((arr * 255).astype(np.uint8), "L")
    if blur > 0:
        alpha_mod = alpha_mod.filter(ImageFilter.GaussianBlur(radius=blur))

    # Solid foreground tinted with the target ink colour.
    fg = Image.new("RGBA", alpha.size, (*ink_color, 255))
    fg.putalpha(alpha_mod)

    white_bg = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    result = Image.alpha_composite(white_bg, fg)
    return result.convert("RGB")


def jpeg_bake(image: Image.Image, quality: int = JPEG_QUALITY) -> Image.Image:
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=quality, subsampling=2, optimize=False)
    buf.seek(0)
    return Image.open(buf).copy()


# ── Scan parameters ─────────────────────────────────────────────────────────
def scan_parameters(ref_metrics: dict) -> list[dict]:
    """Generate parameter combinations to test."""
    combos = []
    for gamma in [1.0, 1.5, 1.8, 2.2, 2.5]:
        for opacity in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            for blur in [0.3, 0.5, 0.7, 1.0, 1.3]:
                combos.append({"gamma": gamma, "opacity": opacity, "blur": blur})
    return combos


# ── Full composite onto page ────────────────────────────────────────────────
def composite_onto_page(
    page: Image.Image,
    alpha: Image.Image,
    x: int, y: int,
    gamma: float,
    opacity: float,
    blur: float,
    ink_color: tuple[int, int, int],
) -> Image.Image:
    """Composite with tuned parameters and target ink colour."""
    arr = np.asarray(alpha, dtype=np.float32) / 255.0
    arr = np.power(np.clip(arr, 0.0, 1.0), gamma) * opacity
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


def scanner_effect(image: Image.Image, box: tuple, sigma: float = NOISE_SIGMA, seed: int = 42) -> Image.Image:
    rng = np.random.default_rng(seed)
    src = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = src.shape[:2]
    noise = rng.normal(0, sigma, (h, w, 1))
    row_noise = rng.normal(0, 0.15, (h, 1, 1))
    processed = np.clip(src + noise + row_noise, 0, 255)

    x0, y0, x1, y1 = box
    margin = 30
    fx0, fy0 = max(0, x0-margin), max(0, y0-margin)
    fx1, fy1 = min(w, x1+margin), min(h, y1+margin)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle((fx0, fy0, fx1, fy1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=12))
    alpha_n = np.asarray(mask, dtype=np.float32)[..., None] / 255.0
    result = src * (1.0 - alpha_n) + processed * alpha_n
    return Image.fromarray(result.astype(np.uint8), "RGB")


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Sampling ink colour from existing signatures...")
    ink_color = sample_ink_color(PAGE_PATH)

    print("\nLoading page and sampling reference metrics...")
    ref = sample_reference_metrics(PAGE_PATH)

    print("\nBuilding alpha mask from source signature...")
    alpha = build_alpha(SIG_PATH, SCALE)
    # We intentionally do NOT upscale the source RGB — the colour comes from
    # the existing signatures via ink_color.
    fg_size = (round(Image.open(SIG_PATH).width * SCALE),
               round(Image.open(SIG_PATH).height * SCALE))
    print(f"  Alpha mask size: {fg_size}, target ink: {ink_color}")

    combos = scan_parameters(ref)
    print(f"\nTesting {len(combos)} parameter combinations...")

    results = []
    for i, c in enumerate(combos):
        rendered = render_stroke(alpha, c["gamma"], c["opacity"], c["blur"], ink_color)
        baked = jpeg_bake(rendered)
        m = compute_metrics(baked)
        d = distance(ref, m)
        results.append({**c, "metrics": m, "distance": d})
        if i % 30 == 0:
            print(f"  [{i}/{len(combos)}] gamma={c['gamma']} opacity={c['opacity']} blur={c['blur']} -> dist={d:.4f}")

    # Sort by distance (lower = better)
    results.sort(key=lambda r: r["distance"])

    print(f"\nTop 5 matches:")
    for r in results[:5]:
        print(f"  gamma={r['gamma']} opacity={r['opacity']} blur={r['blur']} dist={r['distance']:.4f}  metrics={r['metrics']}")

    best = results[0]
    print(f"\nBest: gamma={best['gamma']}, opacity={best['opacity']}, blur={best['blur']}, ink={ink_color}")

    # Generate final output with best params
    print("\nGenerating final output with best parameters...")
    page = Image.open(PAGE_PATH).convert("RGB")
    composited = composite_onto_page(page, alpha, PLACE_X, PLACE_Y,
                                     best["gamma"], best["opacity"], best["blur"],
                                     ink_color)
    sig_box = (PLACE_X, PLACE_Y, PLACE_X + alpha.width, PLACE_Y + alpha.height)
    noisy = scanner_effect(composited, box=sig_box)
    final = jpeg_bake(noisy)

    final_jpg = OUT_DIR / "test_firma_calibrated.jpg"
    final_png = OUT_DIR / "test_firma_calibrated.png"
    final.save(final_jpg, quality=JPEG_QUALITY, subsampling=2, dpi=(TARGET_DPI, TARGET_DPI))
    final.save(final_png, dpi=(TARGET_DPI, TARGET_DPI))

    # Comparison crop
    crop_box = (max(0, PLACE_X-100), max(0, PLACE_Y-20),
                min(page.width, PLACE_X+alpha.width+100),
                min(page.height, PLACE_Y+alpha.height+20))
    before = page.crop(crop_box).convert("RGB")
    after = final.crop(crop_box).convert("RGB")
    comp = Image.new("RGB", (before.width*2 + 4, before.height))
    comp.paste(before, (0, 0))
    comp.paste(Image.new("RGB", (4, before.height), (0, 200, 0)), (before.width, 0))
    comp.paste(after, (before.width+4, 0))
    comp_path = OUT_DIR / "test_firma_calibrated_comparison.png"
    comp.save(comp_path)

    # Save results JSON
    (OUT_DIR / "test_firma_calibration.json").write_text(
        json.dumps({"ink_color": list(ink_color), "reference": ref, "best": best, "top10": results[:10]}, indent=2),
        encoding="utf-8",
    )

    print(f"\nDone! Outputs:")
    print(f"  {final_jpg}")
    print(f"  {final_png}")
    print(f"  {comp_path}")
    print(f"  {OUT_DIR / 'test_firma_calibration.json'}")
    print(f"  {final_jpg}")
    print(f"  {final_png}")
    print(f"  {comp_path}")


if __name__ == "__main__":
    main()
