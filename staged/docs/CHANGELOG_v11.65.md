# NIKE Lab Tools v11.65

## Defecation cycle analysis — cockpit landmark picking

- Head, tail-tip, and full-body outline picking now happen inside the shared
  NIKE workbench (controls | canvas | hood) instead of separate matplotlib
  pop-up windows.
- The tail tip is placed as an editable crosshair/point in the workbench:
  - zoom/pan for precise placement,
  - **undo** the last point,
  - **clear and redraw**,
  - **cancel** a landmark and try again without closing the tool.
- If a landmark is cancelled or drawn incompletely, the calibration navigator
  simply stays on that landmark so it can be re-traced — no dead-ends.
- Landmark coordinates are still returned in full-resolution **source pixels**,
  identical to the previous flow. The pBoc detection engine, tail-axis motion
  logic, seed outline JSON, and all outputs are **unchanged**.

## Carried forward

- v11.64 basal slowing robustness (no crash on movie/stack-backed sources).
- v11.63 defecation source intake: TIFF stacks, movies, still images, folders.
- v11.62 pharyngeal pumping editable ellipse ROI.
- Hub version label reads live from `version.json` / `release_info.json`.
