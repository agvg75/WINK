# WINK Lab Tools v11.91 — Pharyngeal pumping: in-panel dialogs + moving ROI

Two changes, both scoped to the **Pharyngeal pumping** tool. Pump-detection
maths are unchanged.

## 1. In-panel dialogs (no more pop-ups hiding behind the window)
The value questions the tool asks — frames per second, micrometers per pixel,
exposure, stillness/sensitivity thresholds, and the bout-pause question at save —
used to open separate pop-up windows that, on Windows, often appeared *behind*
the main window and had to be hunted for.

They now render as a small dialog strip at the **top of the Controls column**:
title, prompt, an entry, and OK / Cancel. It blocks like the old dialog (and
keeps you from clicking elsewhere until answered) but never hides behind
anything and doesn't flash windows in and out between questions.

Built on a new reusable helper (`app/inline_prompt.py`) so other modules can
adopt it later; this release wires it into the pharyngeal tool only.

## 2. Moving pharynx ROI (follow the pharynx along a path)
Previously the pharynx ROI was a single fixed box; drawing again just replaced
it. Now:

- Draw the pharynx ROI as usual — **one ROI still behaves as a fixed window.**
- To follow a **moving** pharynx, scroll to a later frame and **draw again over
  the new pharynx position**. Each accepted draw drops an *anchor*. The ROI then
  **follows the interpolated path** between the dropped positions, so a pharynx
  that drifts from position 1 → 2 → 3 → 4 stays inside the measured window.
- The image shows the numbered anchors, the connecting path, and the ROI box at
  its interpolated position for the current frame.
- **Remove ROI here** deletes the anchor at the current frame; **Clear all ROIs**
  resets the path.
- Analysis measures along the path (`analyze_along_trajectory`, with a per-frame
  local template refine); with a single anchor it uses the classic fixed-ROI
  analyzer exactly as before.
- Anchors placed before analysis **carry into Guided review (3b)**, where you can
  keep dropping/correcting them and re-count.

## Under the hood
- Dual-support on the update channel unchanged (published under both
  `WINK_Lab_Tools_v11.91_Current_Files` and `NIKE_…`).
