# NIKE Lab Tools v11.75

## Pharyngeal guided review — choose the trace method

The guided (drop-anchor) review can now measure pumping along your anchor
trajectory with **either** method:

- **Template deformation** — the dominant-deformation SVD trace, and
- **PumpKin-style motion compensation** — the residual optical-flow trace.

Details:

- The guided review starts with whichever your **"Use PumpKin motion
  compensation"** checkbox is set to on the main panel.
- A new **"Switch method (template / motion)"** button re-runs the analysis
  along the *same* anchors, so you can compare the two on the identical
  trajectory and pick whichever reads cleaner for your recording.
- The active method is shown in the process hood and the status bar.

Only the choice of which trace feeds the shared, unchanged pump-peak detector
varies — the biphasic peak logic and thresholds are the same for both.

### Still available
- The standard **Analyze interval** (single static ROI) and **AUTO: full
  recording** paths are unchanged.
