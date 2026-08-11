"""Analyze campione_tratto.png: extract ink profile, edge quality, noise.

This gives us the "DNA" of the existing pen strokes so we can replicate
the exact look in our composite signature.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
import json

SAMPLE_PATH = Path(r"c:\Users\maurizio\Documents\pdfnow\campione_tratto.png")
OUT_DIR = Path(r"c:\Users\maurizio\Documents\pdfnow\export")


def analyze(sample_path: Path) -> dict:
    im = Image.open(sample_path).convert("L")
    arr = np.asarray(im, dtype=np.float32)
    h, w = arr.shape
    print(f"Sample size: {w}×{h}")

    # ── 1. Background vs ink levels ────────────────────────────────────
    bg = float(np.percentile(arr, 95))      # paper white
    core = float(np.percentile(arr, 2))     # darkest ink
    mid = float(np.median(arr))             # overall median
    print(f"\nTonal range: bg={bg:.0f}  core ink={core:.0f}  median={mid:.0f}")

    # ── 2. Cross-sectional profile ─────────────────────────────────────
    # Take several horizontal scanlines through the stroke, average them.
    # Find rows that contain ink (variance > threshold).
    row_var = np.var(arr, axis=1)
    ink_rows = np.where(row_var > np.percentile(row_var, 80))[0]
    print(f"\nInk-containing rows: {len(ink_rows)}/{h}")

    if len(ink_rows) > 0:
        # Average profile across ink rows, centered on the darkest column
        profiles = []
        edge_widths = []
        stroke_widths = []

        for row in ink_rows:
            profile = 255 - arr[row, :]  # darkness profile (0=paper, 255=ink)
            profiles.append(profile)

            # Find the stroke in this row
            dark = profile > np.percentile(profile, 50)
            if dark.sum() < 3:
                continue

            # Stroke width (pixels where darkness > 10% of max)
            threshold = profile.max() * 0.1
            stroke_px = (profile > threshold).sum()
            stroke_widths.append(stroke_px)

            # Edge width: pixels from 10% to 90% of max darkness
            rising_edge = np.where(np.diff(dark.astype(int)) == 1)[0]
            falling_edge = np.where(np.diff(dark.astype(int)) == -1)[0]
            for e in list(rising_edge) + list(falling_edge):
                if 5 < e < w - 5:
                    # Width of transition zone
                    zone = profile[max(0, e-4):min(w, e+5)]
                    rise = np.where((zone > zone.max()*0.1) & (zone < zone.max()*0.9))[0]
                    if len(rise) > 0:
                        edge_widths.append(len(rise))

        avg_profile = np.mean(profiles, axis=0)
        median_stroke_w = float(np.median(stroke_widths)) if stroke_widths else 0
        median_edge_w = float(np.median(edge_widths)) if edge_widths else 0

        print(f"Median stroke width: {median_stroke_w:.1f} px")
        print(f"Median edge transition: {median_edge_w:.1f} px")

        # Find the peak and extract the cross-section
        peak_col = int(np.argmax(avg_profile))
        half_w = int(median_stroke_w / 2) + 4
        x0 = max(0, peak_col - half_w)
        x1 = min(w, peak_col + half_w)
        cross_section = avg_profile[x0:x1]
        cross_x = np.arange(len(cross_section))

        # Normalize cross-section to [0, 1]
        cs_norm = (cross_section - cross_section.min()) / max(cross_section.max() - cross_section.min(), 1)
    else:
        median_stroke_w = 0
        median_edge_w = 0
        cs_norm = np.array([])
        cross_x = np.array([])

    # ── 3. Noise analysis ──────────────────────────────────────────────
    # High-frequency residual after Gaussian blur
    blurred = np.asarray(Image.fromarray(arr.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)), np.float32)
    residual = arr - blurred
    noise_std = float(np.std(residual))
    print(f"\nNoise σ (high-freq residual): {noise_std:.2f}")

    # ── 4. Edge gradient sharpness ─────────────────────────────────────
    gy = np.diff(arr, axis=0)
    gx = np.diff(arr, axis=1)
    edge_strength = float(np.mean(np.abs(gx)) + np.mean(np.abs(gy)))
    print(f"Edge gradient strength: {edge_strength:.2f}")

    return {
        "sample_size": [w, h],
        "bg_level": bg,
        "core_ink_level": core,
        "stroke_width_px": median_stroke_w,
        "edge_width_px": median_edge_w,
        "noise_sigma": noise_std,
        "edge_gradient": edge_strength,
        "cross_section": cs_norm.tolist() if len(cs_norm) > 0 else [],
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = analyze(SAMPLE_PATH)
    (OUT_DIR / "campione_tratto_analysis.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"\nAnalysis saved to export/campione_tratto_analysis.json")

    # ── Key takeaways for our rendering ────────────────────────────────
    print("\n" + "=" * 60)
    print("IMPLICATIONS FOR SIGNATURE RENDERING:")
    print(f"  Stroke width: ~{results['stroke_width_px']:.1f} px at sample DPI")
    print(f"  Edge transition: ~{results['edge_width_px']:.1f} px (sharpness)")
    print(f"  Noise texture: σ={results['noise_sigma']:.2f}")
    print(f"  Ink density profile saved (cross_section array)")

    if results['edge_width_px'] < 2:
        print("\n  → Edges are SHARP. Use minimal blur (σ ≤ 0.3).")
    else:
        print(f"\n  → Edges are SOFT. Use blur σ ≈ {results['edge_width_px']/3:.1f}.")

    print(f"  → Target non-zero pixels at 300 DPI should be ~{results['stroke_width_px']:.0f}×skeleton_length")


if __name__ == "__main__":
    main()
