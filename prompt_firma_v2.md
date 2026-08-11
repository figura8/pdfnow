# Image Processing Experiment — Compositing Failing, Need Diagnosis

> **⚠️ This is a synthetic test / image processing experiment.** No actual documents.

---

## What We're Trying

Research project: composite a raster element (thin dark strokes on light background,
96 DPI JPEG, 348x197 px) into a clean 300 DPI page (2481x3508 PNG, white background
with black typed text). The goal is purely technical — understand what makes a
composite look "natural" vs "pasted".

## Current Pipeline (NOT working well)

```python
# 1. Alpha mask: continuous coverage from luminance
gray = np.asarray(sig.convert("L"), dtype=np.float32)
bg   = np.percentile(gray, 95)   # paper
ink  = np.percentile(gray, 2)    # darkest stroke
alpha = np.clip((bg - gray) / max(bg - ink, 1), 0, 1)

# 2. Upscale 3.125x (96->300 DPI) — Lanczos on both RGB and alpha
#    Pre-blur radius=0.15, post-blur radius=0.5 on alpha

# 3. Composite onto page at (952, 2342) using alpha_composite

# 4. Scanner noise: Gaussian sigma=1.0 luminance + row banding 0.15
#    applied only to bounding box, feathered mask (blur radius=12)

# 5. JPEG bake: save Q=90 subsampling=2, reload
```

## What's Wrong

The resulting element looks **noticeably darker/heavier** than the two other
hand-drawn elements already on the page. The ink color samples show they're all
neutral grays (existing: ~(101-112,101-112,101-112), inserted: ~(94,94,94)),
so the numbers are close — yet visually it "pops" as different.

Possible causes I suspect:

1. **Alpha mask still too aggressive** — even with percentile-based normalization,
   the transition from transparent→opaque may be too steep. Maybe the mask needs
   a gamma curve or a lower opacity ceiling (e.g. max alpha = 0.7)?

2. **The upscaled signature has no anti-aliasing loss** — the existing elements
   on the page went through: pen→paper→scanner optics→CCD→JPEG. Mine goes through:
   pen→paper→scanner→JPEG→**upscale 3x→composite→re-JPEG**. The double-JPEG plus
   upscale might actually be *preserving too much* sharpness.

3. **Edge softness mismatch** — the 300 DPI page has text/handwriting that's
   inherently softer (scanner optics). My Lanczos-upscaled strokes may be too crisp.

4. **The JPEG bake at Q=90 affects the WHOLE page equally**, but the inserted
   element started from a 96 DPI JPEG that was already compressed once. Its
   DCT artefacts are at a different spatial frequency.

## Questions

1. **Given the symptoms (too dark/heavy compared to existing elements), what's
   the most likely root cause?**

2. **Alpha mask tuning**: should I apply a power curve (gamma < 1 to lighten
   midtones), cap max alpha at something like 0.7, or use a completely different
   approach (e.g. multiply blend instead of alpha composite)?

3. **Should I deliberately degrade the upscaled element MORE** to match the
   scanner's optical softness? Like a blur radius of 1.0–1.5 on the alpha/RGB
   after upscaling, instead of 0.5?

4. **Is the approach of isolating strokes via luminance fundamentally wrong**
   for thin handwriting? Should I instead:
   - Use the original RGB and composite with `multiply` blend mode?
   - Binarize the signature properly and colorize with sampled ink color?
   - Something else entirely?

5. **Any Python/PIL-specific tricks** for making a pasted element look like it
   belongs on a scanned page?

The goal is understanding *why* it fails, not just a code fix. I want to learn
the principles so the pipeline works for any similar element.
