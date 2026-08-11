"""Final signature render with ALL campione_tratto.png discoveries.

Fixes applied:
1. Ink colour: (13, 8, 10) — dark, almost black (NOT 77,77,77!)
2. Power curve 2.8–3.5 for correct stroke width
3. Striation texture — directional noise simulating ball grooves
4. Voids — probabilistic micro-skips (2.5% density from sample)
5. Minimal blur — edges are SHARP per sample analysis
6. Texture transfer from sample
"""
from __future__ import annotations
import io, json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PAGE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\immagine2.png")
SIG_PATH  = Path(r"c:\Users\maurizio\Documents\pdfnow\firma3.png")
SAMPLE    = Path(r"c:\Users\maurizio\Documents\pdfnow\campione_tratto.png")
OUT_DIR   = Path(r"c:\Users\maurizio\Documents\pdfnow\export")

SCALE = 0.35
PLACE_X, PLACE_Y = 952, 2342

# ── From campione analysis ──────────────────────────────────────────────────
INK_COLOR = (0, 0, 0)           # pure black
VOID_DENSITY = 7.00             # 700%
STRIATION_STRENGTH = 5.0        # much stronger ball grooves
SCANNER_NOISE_SIGMA = 1.6       # was 1.3, grainier scan


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


def load_sample_texture(sample_path: Path, target_shape: tuple) -> np.ndarray:
    """Extract and scale the high-freq texture from campione_tratto.png."""
    im = np.asarray(Image.open(sample_path).convert("L"), dtype=np.float32)
    blurred = cv2.GaussianBlur(im, (0, 0), sigmaX=3.0)
    texture = im - blurred
    tex_std = float(np.std(texture[im < 140]))  # std on ink areas
    tex_norm = texture / max(tex_std, 0.1)

    # Tile to target shape
    h, w = target_shape
    th, tw = tex_norm.shape
    tiled = np.tile(tex_norm, ((h + th - 1)//th, (w + tw - 1)//tw))[:h, :w]
    return tiled


def add_striations(alpha: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Add directional linear noise simulating ballpoint grooves.

    Ballpoint pens leave microscopic grooves along the stroke direction.
    We simulate this with anisotropic Gaussian noise (elongated vertically).
    """
    h, w = alpha.shape
    # Generate noise elongated in one direction (simulating stroke grooves)
    noise = rng.normal(0, 0.06, (h, w))
    # Stretch vertically using Gaussian blur only in Y direction
    noise_stretched = cv2.GaussianBlur(noise, (1, 7), sigmaX=0.5, sigmaY=2.0)
    # Only on ink
    ink = alpha > 0.02
    result = alpha.copy()
    result[ink] = np.clip(alpha[ink] + noise_stretched[ink] * STRIATION_STRENGTH, 0, 1)
    return result


def add_voids(alpha: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Add probabilistic micro-voids (pen skips)."""
    ink = alpha > 0.02
    n_ink = int(ink.sum())
    if n_ink == 0:
        return alpha

    n_voids = int(n_ink * VOID_DENSITY)
    result = alpha.copy()
    ys = rng.integers(0, alpha.shape[0], n_voids)
    xs = rng.integers(0, alpha.shape[1], n_voids)
    for y, x in zip(ys, xs):
        if alpha[y, x] > 0.3:
            result[y, x] *= rng.uniform(0.4, 0.75)
    return result


def composite_page(page, alpha_arr, x, y, blur, ink):
    img = Image.fromarray((alpha_arr * 255).astype(np.uint8), "L")
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    fg = Image.new("RGBA", img.size, (*ink, 255))
    fg.putalpha(img)
    layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
    layer.alpha_composite(fg, dest=(x, y))
    return Image.alpha_composite(page.convert("RGBA"), layer).convert("RGB")


def scanner_noise(image, box, sigma=1.0, seed=42):
    rng = np.random.default_rng(seed)
    src = np.asarray(image.convert("RGB"), dtype=np.float32)
    h, w = src.shape[:2]
    noise = rng.normal(0, sigma, (h, w, 1))
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
    rng = np.random.default_rng(7)
    page = Image.open(PAGE_PATH).convert("RGB")

    print(f"Ink colour: {INK_COLOR}")
    print("Building alpha...")
    alpha = build_alpha(SIG_PATH, SCALE)
    print(f"  Alpha: {alpha.shape[1]}x{alpha.shape[0]}")

    print("Loading sample texture...")
    tex = load_sample_texture(SAMPLE, alpha.shape)
    print(f"  Texture field: {tex.shape}")

    for power, blur, label in [
        (2.5, 0.8, "v22_p25"),
        (2.8, 0.8, "v22_p28"),
    ]:
        print(f"\nPower={power} blur={blur} ...")

        # Thin via power curve
        thinned = np.power(np.clip(alpha, 0, 1), power)

        # Add striations (ball grooves)
        thinned = add_striations(thinned, rng)

        # Add voids (pen skips)
        thinned = add_voids(thinned, rng)

        # Transfer paper/ink texture
        ink_zone = thinned > 0.02
        thinned[ink_zone] = np.clip(thinned[ink_zone] + tex[ink_zone] * 0.06, 0, 1)

        nz = int((thinned > 0.01).sum())
        print(f"  non-zero: {nz}")

        comp = composite_page(page, thinned, PLACE_X, PLACE_Y, blur, INK_COLOR)
        box = (PLACE_X, PLACE_Y, PLACE_X + thinned.shape[1], PLACE_Y + thinned.shape[0])
        noisy = scanner_noise(comp, box, sigma=SCANNER_NOISE_SIGMA)
        final = jpeg_bake(noisy)
        final.save(OUT_DIR / f"firma3_{label}.png", dpi=(300, 300))

    print("\nDone!")


if __name__ == "__main__":
    main()
