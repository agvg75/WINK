# NIKE Lab Tools v11.74

## Track one worm — partial-interval analysis (W5)

- After the recording loads, you're asked (optionally) for a **frame range to
  keep** — e.g. `60-900`, `1-500`, or blank for the whole recording.
- Only that interval is then tracked and reviewed, so you can **skip a noisy
  lead-in or tail** without editing files.
- Works for both small (in-memory) and large (disk-backed) movies: large movies
  use a lightweight frame-window view, so no extra copy of the movie is made.
- The review window and outputs run over the chosen interval (frame 1 = the
  first kept frame); the load message records which original frames were
  analysed (e.g. "analysing frames 60-900 of 1200").

Combined with the v11.73 time-dependent exclude regions, you can now restrict
the worm search in **space** (focus/exclude ROIs, each with a frame range) and
in **time** (analysis interval).

### Note
This currently keeps one contiguous interval. To exclude a noisy section in the
*middle*, analyse the two good stretches separately (a multi-interval option can
be added later if useful).
