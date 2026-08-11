"""Render using the EMPIRICAL ink profile from campione_tratto.png.

Instead of generic power curves or distance-transform soft edges, we use
the actual measured ink density cross-section from the existing signatures.

Profile: 26 px, FWHM=22 px, edge transition=4 px at sample resolution.
We resample it to match the target stroke width at 300 DPI.
"""
from __future__ import annotations
import io, json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from skimage.morphology import skeletonize
from scipy.interpolate import interp1d

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma3.png")
PROFILE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\export\ink_profile.json")
OUT_DIR = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 0.35
PLACE_X, PLACE_Y = 952, 2342
INK_COLOR = (77, 77, 77)


def load_profile() -> interp1d:
    """Load empirical ink profile and return an interpolator.

    Maps normalized distance from center [0, 1] → alpha [0, 1].
    """
    with open(PROFILE_PATH) as f:
        raw = np.array(json.load(f), dtype=np.float32)

    # The profile is symmetric-ish. Take the rising half + peak.
    peak_idx = int(np.argmax(raw))
    rising = raw[:peak_idx+1]  # from edge to center

    # Normalize position to [0, 1] where 0=edge, 1=center
    x_norm = np.linspace(0, 1, len(rising))

    return interp1d(x_norm, rising, kind='cubic', bounds_error=False, fill_value=0.0)


def build_binary(sig_path, scale):
    im = Image.open(sig_path)
    src = np.asarray(im.convert("RGB")).mean(axis=2).astype(np.float32)
    bg = float(np.percentile(src, 95))
    ink = float(np.percentile(src, 2))
    alpha = np.clip((bg - src) / max(bg - ink, 1.0), 0.0, 1.0)
    alpha_img = Image.fromarray((alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=0.15))
    tw, th = round(im.width * scale), round(im.height * scale)
    alpha_img = alpha_img.resize((tw, th), Image.Resampling.LANCZOS)
    arr = np.asarray(alpha_img, dtype=np.float32) / 255.0
    return (arr > 0.5).astype(np.uint8)


def profile_dilate(skeleton: np.ndarray, radius_px: float,
                   profile: interp1d, noise_sigma: float = 0.04) -> np.ndarray:
    """Dilate skeleton and apply empirical ink profile instead of linear fade.

    distance_from_center / radius_px → normalized [0,1] → profile lookup → alpha.
    """
    if skeleton.sum() == 0:
        return np.zeros_like(skeleton, dtype=np.float32)

    # Dilate skeleton to cover the full stroke area
    kernel_size = max(3, int(round(radius_px * 2 + 1)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    iterations = max(1, int(round(radius_px)))
    dilated = cv2.dilate(skeleton.astype(np.uint8) * 255, kernel, iterations=iterations)

    # Distance transform: distance from each pixel to nearest non-stroke pixel
    dist = cv2.distanceTransform(dilated, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)

    # Normalize: 0 = edge of dilated region, 1 = center (distance = radius)
    dist_norm = np.clip(dist / max(radius_px, 0.3), 0.0, 1.0)

    # Apply empirical profile (shifted so edge → 0)
    baseline = float(profile(0.0))
    alpha = np.clip((profile(dist_norm) - baseline) / max(1.0 - baseline, 0.01), 0.0, 1.0)

    # Add subtle noise matching the sample texture
    rng = np.random.default_rng(7)
    h, w = dist.shape
    noise = rng.normal(0, noise_sigma, (h, w))
    noise = cv2.GaussianBlur(noise, (5, 5), 2.0)
    # Noise only where there's ink
    alpha = alpha + noise * (alpha > 0.02)

    return np.clip(alpha, 0.0, 1.0)


def composite_page(page, alpha_arr, x, y, blur, ink):
    img = Image.fromarray((alpha_arr * 255).astype(np.uint8), "L")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", img.size, (*ink, 255))
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


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading empirical ink profile...")
    profile = load_profile()
    print(f"  Profile ready (cubic interpolation)")

    page = Image.open(PAGE_PATH).convert("RGB")

    print("Building binary + skeleton...")
    binary = build_binary(SIG_PATH, SCALE)
    skeleton = skeletonize(binary > 0).astype(np.uint8)
    print(f"  Skeleton: {skeleton.sum()} px, {skeleton.shape[1]}x{skeleton.shape[0]}")

    # Try different radii with the empirical profile
    for radius, blur, noise_s, label in [
        (0.5, 0.15, 0.03, "profile_r05"),
        (0.7, 0.15, 0.03, "profile_r07"),
        (0.7, 0.0,  0.03, "profile_r07s"),
        (0.9, 0.15, 0.03, "profile_r09"),
    ]:
        print(f"Rendering r={radius} σ={blur} ({label})...")
        alpha = profile_dilate(skeleton, radius, profile, noise_sigma=noise_s)
        nz = int((alpha > 0.01).sum())
        print(f"  non-zero: {nz}")
        comp = composite_page(page, alpha, PLACE_X, PLACE_Y, blur, INK_COLOR)
        box = (PLACE_X, PLACE_Y, PLACE_X + alpha.shape[1], PLACE_Y + alpha.shape[0])
        noisy = scanner_noise(comp, box)
        final = jpeg_bake(noisy)
        final.save(OUT_DIR / f"firma3_{label}.png", dpi=(300, 300))

    print("Done!")


if __name__ == "__main__":
    main()
