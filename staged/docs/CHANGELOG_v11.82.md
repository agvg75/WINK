# NIKE Lab Tools v11.82

## Mechanosensation — before / during / after quantification

Analysis now writes a **`reversal_window_metrics.csv`** next to the other
outputs, with one row per trial and, for the **before** (pre-stimulus),
**during** (response), and **after** windows:

- **mean crawling velocity** (body lengths/s) — so response vs baseline is
  explicit (a `velocity_change_during_minus_before` column is included);
- **head-bend amplitude** = robust peak-to-peak (95th − 5th percentile) of
  `head_bend_deg` (degrees), with a `..._change_during_minus_before` column;
- **quirkiness (box aspect ratio)** — Tierpsy-style major/minor axis ratio of
  the worm from the spine points (straight ≈ large, coiled ≈ 1);
- **path tortuosity** — centroid path length ÷ net displacement (the
  spine-independent fallback for when the segmentation is too poor for the box
  ratio).

Notes:

- This is **additive**: it does not change the reversal-response scoring or the
  habituation analysis — those are unchanged. The new columns are descriptive.
- The metric math (percentile amplitude, tortuosity, PCA box-aspect,
  window splitting) was unit-tested.
- Windows default to before = 3 s, response = 5 s, after = 3 s.

### Remaining
- **Spontaneous reversal auto-detection** (a "spontaneous" design/category that
  finds every forward→reverse crossing and quantifies each) is the last piece.
- Interactive scroll-and-mark stimulus timing.
