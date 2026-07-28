# NIKE Lab Tools v11.62

Pharyngeal pumping editable ROI pass.

- Added a reusable `TkCanvasEllipseEditor` helper for module canvases.
- The pharyngeal pumping ROI is now editable before acceptance:
  drag to draw, drag handles to resize, drag inside/center to move, then
  press Enter or the `Accept ROI` button.
- Right-click or Esc cancels ROI editing and preserves the previous ROI.
- The pharyngeal hood now records when the editable ROI editor opens,
  when the ROI is saved, and when editing is cancelled.
- Existing pharyngeal pumping analysis formulas and PumpKin-style option were
  not changed in this pass.

