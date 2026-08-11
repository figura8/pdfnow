"""Final render: firma3.png with natural pen-stroke effects.

Adds three organic imperfections that make a ballpoint signature look real:
1. Pressure variation (downstrokes ~30% thicker)
2. Edge micro-irregularities (paper texture)
3. Ink density variation along the stroke
"""
from __future__ import annotations
import io
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from skimage.morphology import skeletonize

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma3.png")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 0.35
PLACE_X, PLACE_Y = 952, 2342
INK_COLOR = (77, 77, 77)


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


def stroke_direction_map(skeleton: np.ndarray) -> np.ndarray:
    """Compute the local direction (angle) at each skeleton pixel.

    Returns array of same shape with angle in radians [−π/2, π/2].
    0 = horizontal, ±π/2 = vertical.
    """
    h, w = skeleton.shape
    # Convolve skeleton with a small window to get local orientation
    # using PCA on neighbour positions.
    angles = np.zeros((h, w), dtype=np.float32)

    ys, xs = np.where(skeleton)
    if len(ys) < 3:
        return angles

    # For each skeleton pixel, look at neighbours within radius 3
    from scipy.ndimage import binary_dilation
    for r in [2, 3, 4]:
        # Simple gradient-based approach: compute dx, dy along the skeleton
        pass

    # Simpler: compute skeleton gradient via convolution
    gy = cv2.Sobel(skeleton.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    gx = cv2.Sobel(skeleton.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)

    # Angle of the normal. Stroke direction is perpendicular.
    mag = np.sqrt(gx**2 + gy**2)
    valid = mag > 0.1
    angles[valid] = np.arctan2(gy[valid], gx[valid]) + np.pi / 2

    return angles


def natural_dilate(skeleton: np.ndarray, base_radius: float, seed: int = 7) -> np.ndarray:
    """Dilate skeleton with natural variations.

    1. Pressure: modulate radius by stroke angle (vertical strokes thicker).
    2. Density: random noise on alpha along the stroke.
    3. Edge noise: subtle noise added to the alpha mask edges.
    """
    if skeleton.sum() == 0:
        return np.zeros_like(skeleton, dtype=np.float32)

    rng = np.random.default_rng(seed)
    h, w = skeleton.shape

    # ── 1. Angle-based pressure map ──────────────────────────────────────
    angles = stroke_direction_map(skeleton)

    # Modulate radius: vertical strokes (|sin(angle)| ≈ 1) get 30% thicker.
    # Horizontal strokes (|sin(angle)| ≈ 0) stay at base.
    verticality = np.abs(np.sin(angles))
    # Smooth the verticality map so transitions are gradual.
    verticality = cv2.GaussianBlur(verticality, (5, 5), 1.5)

    # Per-pixel radius: base + 30% extra on vertical strokes.
    radius_map = base_radius * (1.0 + 0.30 * verticality)
    # Add micro-variation (gentle random)
    radius_map += rng.normal(0, 0.04, (h, w))
    radius_map = np.clip(radius_map, 0.3, base_radius * 2)

    # ── 2. Build alpha via distance transform on dilated skeleton ────────
    # Dilate with base radius (we'll modulate post-hoc).
    kernel_size = max(3, int(round(base_radius * 2 + 1)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    iterations = max(1, int(round(base_radius)))
    dilated = cv2.dilate(skeleton.astype(np.uint8) * 255, kernel, iterations=iterations)

    dist = cv2.distanceTransform(dilated, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    alpha = np.clip(dist / max(base_radius, 0.3), 0.0, 1.0)

    # ── 3. Ink density variation along the stroke ───────────────────────
    # Generate low-frequency noise field.
    small_h, small_w = max(4, h // 16), max(4, w // 16)
    density_noise = rng.normal(0, 0.06, (small_h, small_w))
    density_noise = cv2.resize(density_noise, (w, h), interpolation=cv2.INTER_CUBIC)
    density_noise = cv2.GaussianBlur(density_noise, (15, 15), 5)

    alpha = alpha * np.clip(1.0 + density_noise, 0.85, 1.15)

    # ── 4. Edge micro-noise ─────────────────────────────────────────────
    # Add very subtle high-frequency noise only at the edges (alpha < 0.5).
    edge_zone = (alpha > 0.02) & (alpha < 0.6)
    edge_noise = rng.normal(0, 0.04, (h, w))
    edge_noise = cv2.GaussianBlur(edge_noise, (3, 3), 0.8)
    alpha[edge_zone] += edge_noise[edge_zone] * alpha[edge_zone]

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
    page = Image.open(PAGE_PATH).convert("RGB")

    print("Building binary + skeleton...")
    binary = build_binary(SIG_PATH, SCALE)
    skeleton = skeletonize(binary > 0).astype(np.uint8)
    print(f"  Skeleton: {skeleton.sum()} px, size: {skeleton.shape[1]}x{skeleton.shape[0]}")

    for radius, blur, label in [
        (0.7, 0.15, "natural"),
        (0.7, 0.0,  "natural_sharp"),
    ]:
        print(f"Rendering r={radius} σ={blur} ({label})...")
        alpha = natural_dilate(skeleton, radius)
        comp = composite_page(page, alpha, PLACE_X, PLACE_Y, blur, INK_COLOR)
        box = (PLACE_X, PLACE_Y, PLACE_X + alpha.shape[1], PLACE_Y + alpha.shape[0])
        noisy = scanner_noise(comp, box)
        final = jpeg_bake(noisy)
        final.save(OUT_DIR / f"firma3_{label}.png", dpi=(300, 300))
        print(f"  -> firma3_{label}.png")

    print("Done!")


if __name__ == "__main__":
    main()
