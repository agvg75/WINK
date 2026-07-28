# NIKE Lab Tools v11.67

## Pharyngeal pumping — guided review with corrective anchors (rebuilt)

A new **"3b. Guided review (drop anchors)"** button opens a correctable,
visually-inspectable review of the approved interval:

- The interval plays in the workbench with the **pharynx ROI drawn on every
  frame**.
- On frames where a pump was counted the ROI turns **green and blinks**, so you
  can see exactly where events land.
- **Left-click the pharynx** to drop or move an **anchor** at the current frame.
  Drop anchors wherever the pharynx moves or the worm changes direction.
- **Reanalyze along anchors** interpolates the ROI trajectory between your
  anchors ("connects the dots") and re-counts pumps in every intervening frame.
- A live **trace with the counted pumps** and **threshold +/-** controls sit in
  the same window (no separate pop-up), with the process hood on the right.
- **Save reviewed detections** writes the same CSV as the standard path.

Notes:

- This is a rebuild of a feature the earlier tool had; it is **new code** and
  benefits from hands-on validation. Please report anything that misbehaves.
- The existing **Analyze interval** (single ROI, template or PumpKin-style
  motion compensation) and **AUTO: full recording** paths are unchanged, so you
  can still choose between approaches.
- Pump-detection maths are unchanged: only the ROI *position* varies per frame,
  using the same deformation-trace and biphasic peak formula.

## Carried forward

- v11.66 worm search focus/exclude ROIs; workbench min/max window buttons.
- v11.65 defecation cockpit landmark picking; and earlier fixes.
