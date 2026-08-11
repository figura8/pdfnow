# Image Processing Theory: Why Composited Elements Look Fake on Scanned Pages

I'm researching image compositing for a computer vision project. I have a purely
synthetic test case and I'm hitting a visual quality wall. I need help diagnosing
the *principles*, not fixing specific code.

## Setup (all synthetic/generated)

- **Page**: 300 DPI white image (2481x3508) with black computer-rendered text
  and two simple geometric stroke patterns (circa 500x150 px each).
- **Element to insert**: a 96 DPI JPEG (348x197 px) containing thin dark strokes
  (luminance ~85-110) on near-white background (luminance ~240-250).
- **Goal**: upscale element to 300 DPI, place it on the page, and make it
  visually consistent with the stroke patterns already there.

## Pipeline tried

```
1. Alpha mask: continuous from luminance
   alpha = clip((bg_pct95 - pixel) / (bg_pct95 - ink_pct2), 0, 1)

2. Upscale 3.125x: Lanczos on RGB + alpha
   pre-blur 0.15, post-blur 0.5 (on alpha only)

3. Composite: PIL alpha_composite at target position

4. Noise: Gaussian sigma=1.0 luminance + row banding, feathered mask

5. JPEG: save Q=90 subsampling=2, reload
```

## The Problem (visual, not code)

The inserted element looks **too dark/heavy** compared to the native stroke
patterns. Color sampling says they're similar neutral grays — yet visually
the inserted element "pops" as obviously composited.

## My Hypotheses (which one is right?)

A) **Alpha normalization wrong** — `(bg - pixel) / (bg - ink)` produces alpha=1.0
   for the darkest strokes, but real scanned strokes have sub-100% coverage due to
   scanner optics. Maybe max alpha should be capped at 0.6-0.8?

B) **Frequency mismatch** — the native elements went through: stroke → optical
   blur → CCD sampling → JPEG once. My element goes: stroke → JPEG → upscale 3x
   → composite → JPEG again. The double-JPEG at different resolutions creates
   conflicting DCT artifact frequencies.

C) **Edge statistics** — the native elements have a specific edge gradient profile
   (scanner MTF). My Lanczos-upscaled element has a different one (sinc-based).
   The human eye detects the statistical mismatch even if single-pixel colors match.

D) **Alpha compositing is the wrong blend mode** — `over` operator assumes the
   foreground *covers* the background. Real dark strokes on paper are closer to a
   *multiply* or *darken* blend (ink absorbs light, doesn't sit on top).

E) **Something else** I haven't considered.

## What I'm asking

1. Which hypothesis is the most likely root cause? Rank them if possible.

2. For hypothesis D: if multiply/darken is more physically correct for strokes
   on paper, what's the PIL implementation? Just `ImageChops.multiply()` on the
   stroke region, or is there a better approach?

3. For hypothesis A: is there a principled way to determine the correct max alpha
   for scanned strokes, or is it always heuristic?

4. Is there any academic/industry literature on the perceptual factors that make
   composited elements look "pasted" vs "native" in document images?

This is pure image processing theory — no documents, no signatures, no real data.
Just synthetic test patterns and signal processing principles.
