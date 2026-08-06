"""The probe measures a recording; the standard document must match the code.

Two things are checked here.

FIRST, that the probe measures what it claims. Synthetic clips are built with
a known animal size and frame rate, and the probe has to recover the size and
the checker has to reach the right verdict - including on the two clips built
to fail, since a checker that passes everything is worse than none.

SECOND, that docs/ACQUISITION_STANDARD.md agrees with acquisition_check.py.
The document is the thing Mackenzie reads at the scope; the module is the
thing the tools obey. A number that appears in one and not the other is how a
standard quietly stops being the standard. Written after the swimming row was
found saying 16 fps where recommend() says 20.
"""
from pathlib import Path
import re
import shutil
import sys
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools" / "population_swimming"),
                str(ROOT / "tools" / "acquisition_standard")]

import acquisition_check as ac        # noqa: E402
import acquisition_probe as ap        # noqa: E402
from check_acquisition import ASSAY_WANTS, ASSAY_GAIT   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("acquisition probe and standard\n")


def make_clip(folder, body_px, n_frames=24, W=640, H=480, n_worms=5):
    """Undulating animals on an unevenly lit plate, at a known body size."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W]
    base = 70 + 45 * np.exp(-(((xx - W / 2) / (0.8 * W)) ** 2
                              + ((yy - H / 2) / (0.8 * H)) ** 2))
    # Kept clear of the edges: an animal clipped by the frame measures short,
    # which is a property of the fixture rather than of the probe.
    margin = body_px * 0.8 + 20
    centres = rng.uniform([margin, margin], [W - margin, H - margin],
                          size=(n_worms, 2))
    headings = rng.uniform(0, 2 * np.pi, n_worms)
    width_px = max(2, int(round(body_px * 80 / 1150)))
    for f in range(n_frames):
        img = np.clip(base + rng.normal(0, 9, (H, W)), 0, 255).astype(np.uint8)
        for k in range(n_worms):
            cx, cy = centres[k]
            s = np.linspace(-body_px / 2, body_px / 2, 24)
            phase = 2 * np.pi * (f / n_frames + k / n_worms)
            lateral = 0.10 * body_px * np.sin(2 * np.pi * s / body_px + phase)
            ux, uy = np.cos(headings[k]), np.sin(headings[k])
            pts = np.stack([cx + s * ux - lateral * uy,
                            cy + s * uy + lateral * ux], 1).astype(np.int32)
            cv2.polylines(img, [pts], False, 210, width_px)
        cv2.imwrite(str(folder / f"frame_{f:04d}.png"), img)
    return folder


tmp = Path(tempfile.mkdtemp(prefix="wink_acq_"))
try:
    # --- the probe recovers a known animal size --------------------------
    big = make_clip(tmp / "big", 160)
    probe = ap.probe(big, sample_frames=12)
    measured = probe["body_length_px"]
    check("the probe measures an animal without being told the scale",
          measured is not None, f"{measured} px")
    # The contour follows the undulating body, so the measurement is arc
    # length and legitimately exceeds the 160 px end-to-end span.
    check("...recovering the body length to within 35%",
          measured and 160 * 0.85 <= measured <= 160 * 1.35,
          f"{measured:.0f} px against a 160 px span")
    check("...and finding the right number of animals",
          4 <= probe["body_length_detail"]["objects_per_frame"] <= 6,
          f"{probe['body_length_detail']['objects_per_frame']} per frame")

    small = make_clip(tmp / "small", 24)
    small_probe = ap.probe(small, sample_frames=12)
    check("the measurement tracks the animal size",
          small_probe["body_length_px"] < measured / 3,
          f"{small_probe['body_length_px']} px vs {measured:.0f} px")

    # --- segmentation must not require motion ----------------------------
    # Every animal is in the same place in every frame of these fixtures, so
    # a temporal background would contain them and measure only their edges.
    check("a stationary animal is still measured",
          measured and measured > 100,
          "a short test clip is exactly where nothing has moved yet")

    # --- intensity findings ----------------------------------------------
    it = probe["intensity"]
    check("the sensor range in use is reported",
          it["grey_levels_used"] > 50, f"{it['grey_levels_used']} levels")
    check("...and clipping is measured, not assumed",
          it["saturated_fraction"] < ap.SATURATION_TOLERANCE,
          f"{it['saturated_fraction']:.2%} at full scale")

    dark = tmp / "dark"
    dark.mkdir()
    for f in range(6):
        a = np.zeros((240, 320), np.uint8)
        a[100:104, 100:160] = 3          # near-empty, a handful of levels
        cv2.imwrite(str(dark / f"f{f:02d}.png"), a)
    dark_it = ap.measure_intensity([cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
                                    for p in sorted(dark.glob("*.png"))])
    check("a near-empty recording is identified as such",
          dark_it["zero_fraction"] > 0.9 and dark_it["grey_levels_used"] < 10,
          f"{dark_it['zero_fraction']:.0%} zero, "
          f"{dark_it['grey_levels_used']} levels")

    # --- an image folder carries no frame rate, and must not invent one ---
    check("no frame rate is claimed for an image folder",
          probe["header_fps"] is None,
          "movie_core defaults the attribute to 1.0; that is not a "
          "measurement and must not read as one")

    # --- declared numbers are cross-examined -----------------------------
    lying = ap.probe(big, sample_frames=12, um_per_px=1.0)
    check("a scale that disagrees with the animals is caught",
          any("not the animals you think" in d for d in lying["disagreements"]),
          "1 um/px would make a 1140 um animal 1140 px long")
    honest = ap.probe(big, sample_frames=12,
                      um_per_px=ap.measured_um_per_px(measured))
    check("...while a consistent scale passes silently",
          not honest["disagreements"])

    # --- refusals ---------------------------------------------------------
    empty = tmp / "empty"
    empty.mkdir()
    try:
        ap.probe(empty)
        check("an empty folder is refused", False)
    except Exception as exc:
        check("an empty folder is refused", True, type(exc).__name__)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- the document must agree with the code -------------------------------
DOC = (ROOT / "docs" / "ACQUISITION_STANDARD.md").read_text(encoding="utf-8")
check("the standard document exists", bool(DOC.strip()))

for assay, wants in ASSAY_WANTS.items():
    if assay == "all":
        continue
    rec = ac.recommend(wants=wants, gait=ASSAY_GAIT.get(assay, "crawl"))
    row = re.search(rf"^\|[^|]*\|[^|]*\|\s*\*\*{rec['min_fps']:g} fps, "
                    rf"{rec['min_body_px']} px\*\*", DOC, re.M)
    check(f"the per-assay row for {assay} matches recommend()",
          row is not None,
          f"expects {rec['min_fps']:g} fps, {rec['min_body_px']} px")

for key, spec in ac.MEASUREMENTS.items():
    n = spec["samples_per_undulation"]
    crawl = max(n * 0.5, 1)
    swim = max(n * 2, 4)
    # The document must carry the checker's exact label, so a FAIL line the
    # student reads points at a row they can find.
    label = spec["label"]
    row = [ln for ln in DOC.splitlines()
           if ln.startswith("|") and label.lower() in ln.lower()]
    check(f"the measurement row for {key} is in the document", bool(row),
          label)
    if row:
        line = row[0]
        check(f"...with the right pixel floor for {key}",
              re.search(rf"\|\s*\**{spec['min_body_px']}\**\s*\|", line)
              is not None, f"{spec['min_body_px']} px")
        check(f"...and the right frame rates for {key}",
              f"{crawl:g} fps" in line and f"{swim:g} fps" in line,
              f"crawl {crawl:g}, swim {swim:g}")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ACQUISITION_PROBE_PASS")
