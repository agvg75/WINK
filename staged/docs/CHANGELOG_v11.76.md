# NIKE Lab Tools v11.76

## Pharyngeal pumping — analysis graph now inside the main window

Pressing **"3. Analyze interval"** no longer opens a separate review pop-up. The
result is now shown in the main window:

- the **trace with detected pumps** (green dots) appears **below the image**,
- a **detection-threshold** slider and **Save reviewed detections** button appear
  on the **left control panel**, and
- the **process hood** on the right is shared as before.

Threshold changes update the detected pumps live, the title shows the current
pump count and rate, and **"Hide graph"** collapses the panel to give the image
the full height back.

This finishes the original request to keep the analysis graph in the same window
instead of a pop-up, for the standard single-ROI flow. The guided (drop-anchor)
review and the AUTO full-recording path are unchanged.
