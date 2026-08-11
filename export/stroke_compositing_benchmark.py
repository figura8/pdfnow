"""Synthetic benchmark for matching raster strokes across resolutions.

This deliberately uses geometric test patterns rather than handwriting or real
documents.  It produces a contact sheet and a JSON report that make scale,
coverage-gamma, opacity, and optical blur easy to compare.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter


TARGET_DPI = 300
SOURCE_DPI = 96
SCALE = TARGET_DPI / SOURCE_DPI


def geometric_mask(size: tuple[int, int], width: int) -> Image.Image:
    """Return a non-handwriting geometric stroke pattern."""
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    pad = max(8, width * 3)
    points = []
    for x in range(pad, w - pad):
        t = (x - pad) / max(w - 2 * pad - 1, 1)
        y = h * (0.50 + 0.22 * np.sin(t * np.pi * 4))
        points.append((x, int(y)))
    draw.line(points, fill=255, width=width, joint="curve")
    draw.ellipse(
        (int(w * .16), int(h * .22), int(w * .37), int(h * .78)),
        outline=255,
        width=width,
    )
    draw.line(
        (int(w * .64), int(h * .22), int(w * .82), int(h * .78)),
        fill=255,
        width=width,
    )
    draw.line(
        (int(w * .82), int(h * .22), int(w * .64), int(h * .78)),
        fill=255,
        width=width,
    )
    return mask


def jpeg_bake(image: Image.Image, quality: int = 90) -> Image.Image:
    buffer = io.BytesIO()
    image.convert("RGB").save(
        buffer, "JPEG", quality=quality, subsampling=2, optimize=False
    )
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def render_on_paper(
    mask: Image.Image,
    *,
    blur: float,
    gamma: float = 1.0,
    opacity: float = 1.0,
    ink: int = 82,
    seed: int = 7,
) -> Image.Image:
    alpha = np.asarray(mask.filter(ImageFilter.GaussianBlur(blur)), np.float32) / 255
    alpha = np.power(np.clip(alpha, 0, 1), gamma) * opacity
    paper = np.full((*alpha.shape, 3), 246.0, np.float32)
    ink_rgb = np.full_like(paper, float(ink))
    out = paper * (1 - alpha[..., None]) + ink_rgb * alpha[..., None]
    rng = np.random.default_rng(seed)
    out += rng.normal(0, 0.65, (*alpha.shape, 1))
    return Image.fromarray(np.uint8(np.clip(out, 0, 255)), "RGB")


def source_96dpi() -> Image.Image:
    size = (348, 197)
    mask = geometric_mask(size, width=2)
    return jpeg_bake(render_on_paper(mask, blur=.35, seed=11), quality=88)


def mask_from_luminance(image: Image.Image) -> Image.Image:
    gray = np.asarray(image.convert("L"), np.float32)
    background = float(np.percentile(gray, 95))
    ink = float(np.percentile(gray, 2))
    coverage = np.clip((background - gray) / max(background - ink, 1), 0, 1)
    return Image.fromarray(np.uint8(coverage * 255), "L")


def metrics(image: Image.Image) -> dict[str, float]:
    gray = np.asarray(image.convert("L"), np.float32)
    darkness = 246 - gray
    active = darkness > 8
    edges = cv2.Laplacian(gray, cv2.CV_32F)
    return {
        "mean_darkness_active": round(float(darkness[active].mean()), 3),
        "dark_pixel_fraction": round(float((darkness > 35).mean()), 5),
        "edge_energy": round(float(np.mean(np.abs(edges))), 4),
    }


def labelled(label: str, image: Image.Image) -> Image.Image:
    panel = Image.new("RGB", (image.width, image.height + 40), "white")
    panel.paste(image, (0, 40))
    ImageDraw.Draw(panel).text((10, 12), label, fill="black", font=ImageFont.load_default())
    return panel


def run(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    source = source_96dpi()
    source.save(output_dir / "synthetic_source_96dpi.jpg", quality=95, dpi=(96, 96))

    target_size = tuple(round(v * SCALE) for v in source.size)
    native_mask = geometric_mask(target_size, width=6)
    reference = jpeg_bake(render_on_paper(native_mask, blur=.85, seed=19), 90)

    base_mask = mask_from_luminance(source).resize(target_size, Image.Resampling.LANCZOS)
    variants = {
        "reference": reference,
        "naive": render_on_paper(base_mask, blur=.5, gamma=1.0, opacity=1.0),
        "gamma_1.5": render_on_paper(base_mask, blur=.75, gamma=1.5, opacity=.9),
        "gamma_1.8": render_on_paper(base_mask, blur=.9, gamma=1.8, opacity=.85),
        "soft": render_on_paper(base_mask, blur=1.2, gamma=1.6, opacity=.85),
    }
    variants = {name: jpeg_bake(im, 90) for name, im in variants.items()}

    report = {name: metrics(im) for name, im in variants.items()}
    ref = report["reference"]
    for name, values in report.items():
        values["distance_to_reference"] = round(sum(
            abs(values[k] - ref[k]) / max(abs(ref[k]), 1e-6)
            for k in ("mean_darkness_active", "dark_pixel_fraction", "edge_energy")
        ), 4)

    panels = [labelled(name, image) for name, image in variants.items()]
    sheet = Image.new("RGB", (target_size[0], sum(p.height for p in panels)), "white")
    y = 0
    for panel in panels:
        sheet.paste(panel, (0, y))
        y += panel.height
    sheet.save(output_dir / "benchmark_contact_sheet.png", dpi=(300, 300))
    (output_dir / "benchmark_metrics.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("export/benchmark"))
    args = parser.parse_args()
    run(args.output_dir)


if __name__ == "__main__":
    main()
