"""Extract the ink cross-sectional profile from campione_tratto.png.

This profile tells us exactly how the ink transitions from paper→ink→paper
in the existing signatures. We'll use it to replace the generic distance-
transform soft edge in our composite.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image

SAMPLE = Path(r"c:\Users\maurizio\Documents\pdfnow\campione_tratto.png")
OUT_DIR = Path(r"c:\Users\maurizio\Documents\pdfnow\export")


def extract_ink_profile(sample_path: Path) -> np.ndarray:
    """Return a 1D array: the normalized ink density cross-section [0=paper, 1=ink]."""
    im = Image.open(sample_path).convert("L")
    arr = np.asarray(im, dtype=np.float32)
    h, w = arr.shape

    # Convert to darkness (0=paper, 255=ink)
    paper = float(np.percentile(arr, 98))
    darkness = np.clip(paper - arr, 0, 255)

    # Binarize to find stroke regions
    binary = (darkness > 15).astype(np.uint8)

    # Find connected components (individual stroke fragments)
    from scipy.ndimage import label, find_objects
    labeled, n_labels = label(binary)
    print(f"Found {n_labels} stroke fragments")

    # For each fragment, extract perpendicular cross-sections
    profiles = []

    for lbl in range(1, min(n_labels + 1, 50)):  # first 50 fragments
        mask = (labeled == lbl)
        if mask.sum() < 100:  # skip tiny specks
            continue

        ys, xs = np.where(mask)
        y0, y1 = ys.min(), ys.max()
        x0, x1 = xs.min(), xs.max()

        # Fragments that are too wide are probably multiple strokes — skip
        frag_w = x1 - x0
        frag_h = y1 - y0
        if frag_w > 200 or frag_h > 200:
            continue
        if frag_w < 8 or frag_h < 5:
            continue

        # Determine orientation: horizontal or vertical stroke?
        if frag_w > frag_h:
            # Horizontal-ish stroke — sample vertical cross-sections
            for y in range(y0 + 2, y1 - 1):
                row = darkness[y, x0:x1+1]
                if row.max() > 20:
                    # Center on peak
                    peak = np.argmax(row)
                    half_w = 20
                    cs = row[max(0, peak-half_w):min(len(row), peak+half_w)]
                    if len(cs) >= 8:
                        profiles.append(cs / max(cs.max(), 1))
        else:
            # Vertical-ish stroke — sample horizontal cross-sections
            for x in range(x0 + 2, x1 - 1):
                col = darkness[y0:y1+1, x]
                if col.max() > 20:
                    peak = np.argmax(col)
                    half_w = 20
                    cs = col[max(0, peak-half_w):min(len(col), peak+half_w)]
                    if len(cs) >= 8:
                        profiles.append(cs / max(cs.max(), 1))

    if not profiles:
        print("WARNING: no valid profiles found!")
        return np.array([])

    # Align profiles by their center of mass
    max_len = max(len(p) for p in profiles)
    aligned = np.zeros((len(profiles), 2 * max_len))
    for i, p in enumerate(profiles):
        # Center the profile
        com = int(np.average(np.arange(len(p)), weights=p + 0.01))
        offset = max_len - com
        start = max(0, offset)
        end = start + len(p)
        if end > 2 * max_len:
            end = 2 * max_len
            p = p[:end - start]
        aligned[i, start:end] = p[:end-start]

    # Average across all profiles
    avg_profile = aligned.mean(axis=0)

    # Trim to the valid region (where average > 1% of max)
    valid = avg_profile > avg_profile.max() * 0.01
    valid_idx = np.where(valid)[0]
    if len(valid_idx) > 0:
        avg_profile = avg_profile[valid_idx[0]:valid_idx[-1]+1]

    # Normalize
    avg_profile = avg_profile / max(avg_profile.max(), 0.001)

    return avg_profile.astype(np.float32)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Extracting ink profile from campione_tratto.png...")
    profile = extract_ink_profile(SAMPLE)

    if len(profile) == 0:
        print("Failed to extract profile.")
        return

    print(f"Profile length: {len(profile)} px at sample resolution")
    print(f"Profile values: {profile}")

    # Save profile
    profile_path = OUT_DIR / "ink_profile.json"
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile.tolist(), f)
    print(f"Saved: {profile_path}")

    # ── Key metrics ────────────────────────────────────────────────────
    half_max_left = np.where(profile > 0.5)[0][0]
    half_max_right = np.where(profile > 0.5)[0][-1]
    fwhm = half_max_right - half_max_left + 1
    print(f"\nFull Width at Half Maximum: {fwhm} px")
    print(f"Edge width (10%→90%): ", end="")
    rise_10 = np.where(profile > 0.1)[0][0]
    rise_90 = np.where(profile > 0.9)[0][0]
    print(f"{rise_90 - rise_10} px")

    print(f"\nTo use this profile in rendering:")
    print(f"  - Resample from {len(profile)}px to your stroke diameter")
    print(f"  - Use as lookup: alpha = profile_interp[distance_from_center]")
    print(f"  - This replaces the generic 'dist/radius' soft edge")


if __name__ == "__main__":
    main()
