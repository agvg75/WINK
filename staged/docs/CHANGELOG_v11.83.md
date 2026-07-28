# NIKE Lab Tools v11.83

## Mechanosensation — spontaneous reversals + stop-vs-reverse

### Spontaneous reversal auto-detection
- A new **spontaneous** design (in the Design drop-down) needs no stimulus: it
  scans the centroid-derived velocity and detects **every reversal** (a run of
  backward motion past a threshold, lasting at least ~0.25 s).
- Writes **`spontaneous_reversals.csv`** (one row per reversal: onset, peak
  reverse velocity, duration, length) and **`spontaneous_summary.json`**
  (reversal count, **reversals/min**, mean duration / peak / length).
- Works from **centroids**, so it does not require clean spines.

### Stop vs reverse
A response isn't always a reversal — an animal can **stop/pause without
reversing**. The per-trial metrics (`reversal_window_metrics.csv`) now include:
- **`reversed_during`** — did the animal actually reverse in the response window;
- **`stopped_not_reversed`** — did it slow to below half its pre-stimulus forward
  speed without going backward (a pause response);
- **`min_velocity_bl_s_during`** — the most-backward velocity in the response.

Both were unit-tested, and neither changes the existing reversal-response
scoring or habituation analysis.

### Still to come
- **Interactive scroll-and-mark stimulus timing** (mark stimuli on the movie).
- **Population-level assay** (many worms + plate tap → % responding, response
  strength; centroid-based; same stop-vs-reverse and habituation options).
