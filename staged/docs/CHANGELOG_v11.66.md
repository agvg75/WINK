# NIKE Lab Tools v11.66

## Track one worm — focus and exclude regions

- Before tracking, the tool now offers an **optional** guidance step:
  - **Focus region** — draw one shape around the worm and everywhere it
    travels; the search ignores everything **outside** it.
  - **Exclude regions** — draw one or more problem areas (debris, plate edge,
    another animal, a bubble); the search ignores what is **inside** them.
- Regions are drawn on the loaded (cropped) frame and combined into a single
  exclusion mask that is passed to the tracker's existing `exclusion_masks`
  path, so it applies to the initial track **and** to any re-tracking during
  review.
- Fully opt-in: choose **No** at the prompt and tracking behaves exactly as
  before. No measurement formulas changed.

## Workbench windows keep minimize / maximize buttons

- The shared cockpit workbench windows (ROI drawing, egg marking, defecation
  landmarks, pharyngeal review, etc.) were being drawn as **transient** tool
  windows, which on Windows removes the minimize/maximize/restore controls.
- They are now normal top-level windows (with those controls and their own
  taskbar entry) while remaining modal, so they can be minimized and maximized.

## Carried forward

- v11.65 defecation cockpit landmark picking (tail-tip crosshair in the
  shared workbench).
- v11.64 basal slowing robustness; v11.63 defecation source intake;
  v11.62 pharyngeal editable ellipse ROI.
