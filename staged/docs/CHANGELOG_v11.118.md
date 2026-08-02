# WINK Lab Tools v11.118 — failures stop being invisible

Two fixes that make broken things announce themselves instead of failing
quietly. No measurement changes.

## Basal slowing never wrote its decision manifest

`write_decision_manifest` was called with an undefined variable:

```python
try:
    write_decision_manifest(out, "basal_slowing", summary={
        "minimum_window_s": minimum_window_s,   # defined nowhere
        ...})
except Exception as e:
    (out / "decision_transparency_error.txt").write_text(str(e))
```

There is no `minimum_window_s` parameter — the paired comparison is sized by
`before_s` and `after_s`. Because the whole write sits inside a `try/except`
that only records the error to a side file, the `NameError` was swallowed on
**every run since the line was written**: `decision_transparency.json` — the
module's provenance record — was never produced, and the only trace was a stub
nobody reads.

Fixed by recording the parameters that actually exist. A run now writes:

```
before_window_s  8
after_window_s   8
minimum_window_fraction 0.7
minimum_worm_fraction_inside 0.5
tracklet_stitch_max_gap_s 4.0 ...
```

Nothing about the analysis changed; the regression test passed before and
after. Only the provenance record now exists.

## Tk callback failures are reported everywhere, not just in one tool

Tk sends callback exceptions to stderr, which `pythonw` discards. A button whose
handler raises therefore looks exactly like a button that does nothing — the
failure mode that hid Population tracking's dead Confirm/Relabel/Reject buttons
until they were reported by hand.

- `CockpitApp` now installs a handler that writes the failure into the process
  hood and the status line with file and line number. **Eleven tools inherit it**
  in one change: basal slowing, defecation/pBoc, egg counting, egg laying,
  failure library, population tap, myocyte morphometry, paralysis pharmacology,
  pharynx morphometry, Population tracking, single-channel GCaMP.
- Tools that are plain `tk.Tk` rather than cockpit apps get the same behaviour
  through a new shared `install_error_reporting()` helper: pharyngeal pumping,
  mechanosensation, orientation workbench, population orientation, track-derived
  workbench, and the RGBCaMP results browser. Where a tool has no status line
  the failure surfaces as a dialog instead.

Every one of those imports is wrapped in `try/except`, so a diagnostic
convenience can never stop a working tool from starting.

## Audit result: the stale-review bug was not widespread

Population tracking's worst defect — a new analysis silently loading the
*previous* run's reviewed tracks — was checked against every other tool that
reloads prior review state. The pattern
`read_csv(reviewed if reviewed.exists() else fresh)` occurs **nowhere else**.
Egg counting does restore prior human marks, but merges them with fresh
detections rather than replacing them, which is correct. The other tools only
write `reviewed_*` files. No changes were needed and none were made.

## Still outstanding

Basal slowing's area gates default to 40 / 2500 source pixels, the same values
that flood a 4K recording with noise in Population tracking. The
"Measure a worm" helper that fixes this by reading the area the detector gives a
clicked animal is currently specific to Population tracking; generalising it to
a shared component is not done.

Two pre-existing undefined names remain elsewhere, untouched:
`tools/worm_kinematics/worm_kinetics_foraging_dampening.py:167`
(`wave_propagation`) — the same silent-failure shape as the basal slowing one,
and worth the same treatment.
