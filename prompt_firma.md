# Task: Image Processing Experiment — Signature Compositing on Scanned Documents

> **⚠️ DISCLAIMER: This is a synthetic test / image processing experiment.**
> The document is a test fixture created for developing a PDF editing tool (PdfNow).
> The signatures are sample assets, not real legal signatures. The goal is purely
> technical: study how to composite raster elements into a scanned page while
> preserving the visual characteristics of a real scan. No actual document is being altered.

---

## Context

I'm building a Python tool called **PdfNow** for editing scanned PDFs. As part of testing
its image processing pipeline, I have a test scenario: take a scanned page that has
**three handwritten elements** (call them sig-A, sig-B, sig-C), remove sig-A, and
composite a new handwritten element (sig-D) in its place — all while keeping the page
looking like a genuine 300 DPI scan.

The test page has already been rasterized and sig-A digitally removed — the area
is now clean white. Sig-D is available as a separate JPEG. This is a **purely
synthetic test** to validate the compositing + noise-matching pipeline.

## Test Files

| File | Description |
|---|---|
| `immagine2.png` | A4 page at 300 DPI (2481×3508 px), RGB, PNG. Sig-A removed (white area). Two other handwritten elements (sig-B, sig-C) remain. |
| `firma.jpg` | Replacement handwritten element, sig-D (348×197 px at 96 DPI), RGB, JPEG. Dark strokes on light background. Must be scaled to 300 DPI. |

The target area is in the bottom third, roughly rows 2800–3200. The three element
clusters are approximately at:
- cols 460–490
- cols 960–1040
- cols 2140–2260

(One of these is now blank — that's the insertion point for sig-D.)

## Goal

Composite sig-D into the blank area and produce a final page image that looks like a
**genuine 300 DPI scan** — NOT a digital paste job. This is a technical benchmark for
the PdfNow image pipeline.

## The Core Challenge: "Scanned Look" Preservation

A real scan has specific visual signatures that a naive paste destroys:

1. **Optical softness** — scanner optics introduce a sub-pixel blur. Digital ink is too sharp.
2. **Ink bleed / paper texture** — real pen on paper has slight irregularity at the edges.
3. **JPEG compression artifacts** — scanned PDFs typically embed pages as JPEG (Q≈85–92) with characteristic 8×8 DCT blocking.
4. **Color uniformity** — the new strokes should match the existing ones in color/tone.
5. **No "white halo"** — the area around the pasted element must not look brighter or cleaner than the rest of the page.

## Constraints

- **Deterministic pipeline** — no generative AI, no inpainting models.
- **Automatable** — no manual tuning per page.
- **Python only** — PIL/Pillow, OpenCV, NumPy (already in project deps).
- **Output: one page image** → embedded into PDF via PyMuPDF.

---

## My Proposed Pipeline

```
1. PRE-PROCESS firma.jpg
   - Scale 96→300 DPI (≈3.125×, Lanczos)
   - Isolate strokes from background → alpha mask
   - Color-match strokes to existing elements on page

2. POSITION
   - Place in the blank area
   - Alpha-composite using the mask

3. NOISE MATCHING
   - Since the page is clean white PNG, no scanner noise to sample
   - Options: synthetic Gaussian noise, or skip and rely on JPEG step

4. MICRO-BLUR
   - Gaussian σ≈0.3–0.5 px to composited area → simulates scanner optics

5. JPEG RE-COMPRESSION
   - Save as JPEG Q≈90 → introduces DCT blocking artifacts
   - Re-read → bakes artifacts into pixel data

6. EXPORT
   - Embed into PDF at 300 DPI via PyMuPDF
```

---

## Questions for You

1. **Is this pipeline sound?** Missing steps? Overkill?

2. **Noise strategy**: Since the page is pure white where sig-A was removed:
   - (a) Add synthetic Gaussian noise globally, then re-compress?
   - (b) Add noise only to the signature area, feathered at edges?
   - (c) Skip noise, rely only on JPEG compression for "scanned" texture?

3. **Color matching**: Best method to sample stroke color from existing elements and apply to sig-D without destroying stroke texture? HSV shift? Grayscale+colorize? Multiply blend?

4. **Edge treatment**: Alpha feathering vs. gradient dissolve vs. frequency-aware blending?

5. **DPI handling**: sig-D is 96 DPI → needs 3.125× upscale to 300 DPI. Lanczos? Bicubic? Or threshold+binarize and re-render at target resolution?

6. **Alternative approaches**:
   - (a) Composite at full res then JPEG-compress (my proposal)?
   - (b) Downscale everything, composite, then upscale (simulating scan-of-a-scan)?
   - (c) Frequency separation (high-pass strokes, low-pass paper texture)?

7. **Python libraries** beyond PIL/OpenCV/NumPy worth adding? (`scikit-image`, `colour`, etc.)?

---

Please critique the pipeline. The goal is **maximum visual realism with minimum manual steps** — this is a test harness for automated PDF processing, not a one-off edit.

