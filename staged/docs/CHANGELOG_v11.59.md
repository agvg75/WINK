# NIKE Lab Tools v11.59

Workbench architecture pass.

- Added reusable NIKE workbench helpers for the standard module layout:
  controls on the left, interactive canvas in the center, and a hideable
  process/decision hood on the right.
- Pharyngeal pumping threshold review now opens inside the shared workbench
  instead of a separate matplotlib-only window.
- Endpoint egg review controls now use the shared workbench API, preparing the
  earlier calibration, ROI, and reference-egg steps for the same single-window
  migration.
- No measurement formulas were changed in this pass; this update is a UI
  architecture foundation for staged module migration.
- Carries forward v11.58 live pharynx ROI placement/redraw plus earlier
  readiness-label, morphology-preview, egg-learning, and defecation updates.
