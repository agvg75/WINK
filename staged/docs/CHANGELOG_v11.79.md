# NIKE Lab Tools v11.79

## Mechanosensation — track a movie, no manual CSV hand-off (step 1)

The reversal/mechanosensation module is being reworked from a CSV-import tool
into a **track-a-movie-and-quantify-reversals** tool.

This step removes the "weird CSV" friction:

- **"1. Track a movie (auto-loads result)"** now asks for the recording, opens
  the single-worm DIC tracker on it, and — when the tracker window closes —
  **automatically fills in the kinematics CSV** the tracker wrote next to the
  movie. No more exporting and then hunting for the file.
- Manual CSV selection stays as a fallback for anyone who already has a track.
- Stimulus timing stays a simple **time marker** (the "Stimulus times in
  seconds" field). Frames lost to the pick artifact are skipped automatically
  during scoring (non-finite velocity is ignored), while latency stays anchored
  to the entered stimulus time.

### Coming next (step 2)
- **Bending amplitude** during the reversal (from the tracker's per-segment
  curvature / head-bend), added to onset latency, peak velocity, duration, and
  distance.
- **Spontaneous reversal auto-detection** (quantify every direction change, not
  only stimulus-locked ones).
- An explicit **artifact/blackout window** option around the stimulus for
  recordings where the pick lingers.
