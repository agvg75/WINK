# NIKE Lab Tools v11.80

## Mechanosensation — stimulus categories, harsh-touch location, blackout window

- **Stimulus type** is now a drop-down: **nose touch**, **gentle body touch**,
  **harsh body touch**, **population tap** (matching the categories the analysis
  already recognizes).
- **Stimulus location** (anterior / posterior) for **harsh touch**: posterior
  stimuli are expected to evoke a **forward escape** (accelerated forward
  crawling) rather than a reversal — the scorer already detects both a reversal
  and a forward acceleration, so posterior harsh-touch responses are captured.
- **Optional blackout window** (seconds after each stimulus, `0` = off): the
  frames from the stimulus onset through the blackout are marked as artifact and
  **excluded from scoring**, so the pick-in-view interval doesn't corrupt the
  measurement — while **latency stays measured from the entered stimulus time**.

Only the mechanosensation module is affected.

### Coming next (needs your sign-off on the metric definitions)
- **Head-bend amplitude** before / during / after the stimulus (with a
  spine-independent "quirkiness" fallback for bad spines).
- **Spontaneous reversal auto-detection** (a "spontaneous" mode with no stimulus).
- **Before/after crawling baseline** vs response difference.
