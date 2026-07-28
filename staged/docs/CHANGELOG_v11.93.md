# WINK Lab Tools v11.93 — Scale & magnification calculator

A shared spatial-calibration component so every module can get
micrometres-per-pixel the same way. **No measurement maths changed** — this only
helps set the scale that feeds them.

## Three ways to get µm/px (increasing authority)
1. **Optical estimate** — pick the scope (fixes objective + C-mount), enter the
   zoom, pick the camera (fixes sensor pixel pitch):
   `µm/px = pixel_pitch × binning / (objective × zoom × C-mount)`.
2. **Raw scale bar** — draw a line of known length on a frame; µm/px is measured
   directly (no optics needed). Ground truth.
3. **1.14 mm worm check** — trace an adult and compare to the expected length;
   it flags a scale that's off.

## Lab presets (editable, and user additions persist across updates)
- **Scopes:** Olympus SZX12‑A (1× obj, 0.5×C), SZX12‑B (0.5× obj, 0.5×C), Zeiss
  Axioscope (10/20/40/90×). Zoom body vs. fixed-objective handled per scope.
- **Cameras:** Point Grey Flycap2 (4.6 µm), HDMI 4K (~2.4 µm), QImaging optiMOS
  (6.5 µm), ELP SVPro webcam (2.8 µm), Basler (1.85 µm).
- The **ELP webcam** (used directly on plates) and **Basler** (Tierpsy IR rig)
  have no microscope optics, so the optical path is disabled for them and only
  the scale bar applies.
- Notes flag two things to confirm on real footage: the **Zeiss C‑mount adapter
  factor** (often 0.5× or 0.63×) and that an **HDMI‑4K capture may rescale the
  sensor**, so scope B is best calibrated by scale bar.

User-added scopes/cameras are saved under `~/.wink/scale_presets.json`.

## Where it is
- **Standalone:** *Acquisition and utilities → “Scale & magnification
  calculator.”* Open it, compute or measure µm/px, copy the value into any tool.
- **First in-module integration:** the **Pharyngeal pumping** tool now has a
  **“Calibrate scale (µm/px)”** button that opens the same dialog and stores the
  result. Other modules will get the button as they are modernized.

## Honest caveat
The optical estimate is a *predictor* — nominal objective/zoom/adapter values and
rounded sensor specs can be a few percent off. A stage micrometer or the scale
bar remains the authority; the existing declared-vs-measured reconciliation still
flags disagreement.
