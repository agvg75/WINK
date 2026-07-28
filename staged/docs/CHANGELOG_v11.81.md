# NIKE Lab Tools v11.81

## Mechanosensation — experimental design selector

A new **Design** drop-down controls how repeated stimuli are treated:

- **single_trial** — one worm, one stimulus.
- **habituation_series** — the *same* animal(s) stimulated repeatedly. Trials
  keep a shared worm identity, so **stimulus order** and **inter-stimulus
  interval** are preserved and the response can be compared **across trials**
  (the habituation decay fit the analysis already computes now applies to a real
  series).
- **sequential_independent** — different animals stimulated one after another.
  Each stimulus gets its **own** identity, so trials are treated as independent
  replicates rather than a habituation series.

This makes the same reversal quantification usable for both a quick single trial
and a full habituation experiment, just by choosing the design. Only the
mechanosensation module is affected.

### Next
- **Interactive stimulus marking**: scrub the tracked movie and drop a marker at
  each stimulus frame (instead of typing seconds) — especially helpful for a
  long habituation series.
- Paused pending your sign-off: head-bend amplitude (before/during/after) with a
  tortuosity-based "quirkiness" fallback, and spontaneous-reversal detection.
