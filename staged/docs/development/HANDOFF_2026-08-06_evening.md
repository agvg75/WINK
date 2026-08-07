# WINK handoff — 6 August 2026, evening session

Continues `L:\10_AGVG LAB\Lab Tools\_session_archive\SESSION_2026-08-06_INDEX.md`,
which covers the earlier part of the same day. This file covers what came
after, and is written to be read by someone who was not here.

Repo `staged/`, branch `main`, pushed to `https://github.com/agvg75/WINK.git`.

---

## 1. The lessons that generalise

**These are the reason to read this file.** They came out of specific tasks but
they are not about those tasks.

### 1.1 A backlog item names a symptom, not a location

Three of the four items worked on were **reachability failures, not missing
code**:

| item | what the backlog said | what was actually wrong |
|---|---|---|
| basal slowing gates | "`min_area=40` hardcoded near line 691" | the library had derived gates correctly since backlog #12; the **GUI passed 40/2500/60 as explicit overrides on every run** and silently defeated it |
| GCaMP session marks | "no way to commit the selection" | the commit button existed, was correctly wired, and had been **squeezed to one pixel** by a packing bug |
| acquisition standard | "write a checker" | the requirement tables already existed in `acquisition_check.py`, **imported by nothing** |

Now a non-negotiable in `WINK_grant_plan_SPEC.md` section 8: **before fixing
any backlog item, check whether anything imports the module and whether a user
can reach the control.** A fix that was never reachable is not shipped. Budget
for investigation before implementation.

### 1.2 When a measurement is withdrawn, walk forward through what was built on it

This bit twice in one session.

- A body width was measured on a **shadow** rather than the animal and gave
  14.9:1, which appeared to *confirm* an expected 15:1. It was coincidence on
  an invalid measurement.
- `0.45 px/um` was derived from a 495 px body length. The 495 px came from a
  frame census that was **later withdrawn** as a shadow measurement. The 0.45
  survived, and was then compared against a live measurement with the gap
  treated as a real discrepancy needing explanation. There was no discrepancy.

A derived number keeps its apparent independence after its parent dies, and it
is most dangerous when it agrees with an expectation. **Retract forward, in the
same edit.**

### 1.3 Confirm what was segmented before using anything derived from it

Five plausible foreground rules were tried on the pezo-1 CRISPR set. All five
segmented the shadow, the lawn, or a fragment — and every one produced lengths,
widths and scales that looked entirely reasonable. The failure is invisible in
the numbers and obvious the moment the mask is drawn on the raw pixels.

Now written into the motion signature spec as a non-negotiable. **Overlay the
mask and look.**

### 1.4 Domain knowledge beat five rounds of algorithm work

The foreground problem was solved by one sentence from Andres: **"OP50 is
smooth. Worms are textured."** That is not derivable from the pixels — it
requires knowing the substrate is a bacterial lawn, which is also why tracks
exist (worms leave tracks on lawns, not on plain agar) and why the animals feed
there at all.

Preceding attempts — intensity, dark percentile, Otsu, relief dipole, coarse
bandpass — failed because they keyed on darkness or relief, and the lawn has
both. Ask what the thing *is* before tuning a threshold.

### 1.5 A plateau is evidence; a working threshold is not

The texture rule holds the animal stable at 771–779 px across thresholds from
3.5% to 5.5%, with only the speck count changing. That plateau is why the
feature is believed to be right. A single threshold that happens to work is not
evidence of anything.

### 1.6 "Largest component" is an unsafe selector

It returned a fragment of a **different animal** on one frame. A non-worm blob
would have been obviously spurious; a real worm fragment has the right texture,
width and aspect, passes every quality check, and reports the wrong number.

### 1.7 Measure the cheap thing before planning around the expensive one

- `.lif` header reads are **0.13–0.15 s and flat with file size** — a 1.8 GB and
  a 9.6 GB file cost the same, because only the header XML is parsed. Vendor
  format was assumed to be the expensive case; it is not.
- A whole-drive header pass is about **3 minutes**, which makes it a rerunnable
  pass whose thresholds are inputs, not an expensive one-shot.
- The "16-bit" TIFFs carry **7.8–8.2 effective bits** with a quantisation step
  of 128 — 8-bit data left-shifted into a 16-bit word. Converting is lossless.
  Check effective depth before spending effort preserving precision that was
  never captured.

---

## 2. What was committed

| commit | what |
|---|---|
| `2684c70` | basal slowing area gates: derived from the recording, tuned by multiplier |
| `316e344` | ignore the local Claude Code permissions file |
| `697aaaa` | acquisition standard: one-page doc + measuring checker |
| `fe36125` | GCaMP session marks: commit control made clickable, marks persisted |
| `ae27e02` | pumping floor, set from event duration rather than Nyquist |
| `1fdf917` | drive audit proposal pass: depth weighting + `given_name` column |
| `f32a9dc` | grant plan spec with five amendments and two measured numbers |
| `01db269` | pumping spatial floor as a diameter; scale from a known adult; AG/COP strains |
| `b1be75f` | motion signature spec v3, reconstructed, plus the 6.1 correction |
| `d639b53` | illumination geometry and bit depth of the development set |
| `4e87329` | five foreground rules tried, five failed, and why |
| `b601127` | **the working foreground rule** — OP50 smooth, worms striated |
| `dd6bc28` | first run across the frozen six, and the 0.45 px/um retraction |
| `be339e8` | the development set is multi-worm, which invalidated the anchor |

---

## 3. Per-area state

### 3.1 Basal slowing gates — DONE

Raw pixel gates removed from the API entirely; tuning is a multiplier on a
value computed from the recording, with a frame-size fallback when there is no
calibration. 4K regression fixture: the old 40–2500 band admits **0 of 6
animals and 40 of 40 debris specks** — an exact inversion, reported without
raising anything.

Known limitation, recorded in the test rather than tuned away: the uncalibrated
fallback admits 4 of those 40 specks, because 0.1% of frame under-estimates an
adult at 2.5 um/px by about 1.8x.

### 3.2 Acquisition standard — 0.4a DONE, 0.4b is phase 1

`docs/ACQUISITION_STANDARD.md` plus `tools/acquisition_standard/check_acquisition.py`
and `app/acquisition_probe.py`. The test re-derives every doc number from the
code, so the page and the module cannot drift.

**Pumping floor is 30 fps, set from event duration (~150 ms), NOT from the pump
rate via a samples-per-cycle rule.** Pumping is a discrete event, not a
waveform. The reasoning is encoded next to the number because the obvious
"correction" — apply Nyquist like every other row — reintroduces an undercount
that looks entirely plausible.

Spatial floor is a **diameter** (`PHARYNX_BULB_DIAMETER_FRACTION`, 1/33 of body
length), not an axial fraction. The axial version overestimates detectability
about twofold.

**Not done:** 0.4b, the bout budget (`usable_seconds`, `n_bouts`, unusable split
by cause). Needs the bout classifier. Phase 1.

### 3.3 GCaMP session marks — DONE

Layout collapse fixed in `app/frame_range_selector.py`; the AFD neuron tracker
uses the same widget and is fixed with it. Marks now persist through
`app/gcamp_session.py`.

**`segmentation_review` was NOT reused**, despite fitting the shape exactly — it
names `single_channel_gcamp` in `PHOTOMETRY_EXCLUSIONS`. The structural fit is a
trap, and the test pins the exclusion so nobody rediscovers it expensively.

Behaviour surfaced rather than hidden: the selector allows disjoint ranges but
the analysis takes one contiguous span, so marking 0–99 and 300–399 analyses
0–399. `span()` returns the gap and the status line states it.

### 3.4 Drive audit parser — DONE, with a gap for Andres

`tools/drive_audit/propose_labels.py`. Reads `LABEL_ME_L_drive.csv`, writes a
separate proposals file, never touches the input (test asserts byte-identity
after a full run).

Two findings changed the design:

- **The authority could not match the drive at all.** People sheet is keyed by
  surname; the drive is organised by given name. Surnames matched **zero** of
  551 paths while `monica` alone matched 475. A `given_name` column was seeded
  from the lab people page — **39 of 101 rows, the rest need filling by hand** —
  taking authority-backed proposals from 128 to 620 of 1046.
- **94% person coverage was one fact counted 475 times.** A single `\Monica`
  parent is contained in every descendant path. Proposals now carry
  `match_scope`, `scope_rank` and `evidence_group`; the summary reports
  **distinct facts (21) rather than proposals (516)**.

`app/xlsx_lite.py` reads .xlsx with the standard library, because the lab
runtime ships pandas but not openpyxl.

**Owoyemi is NOT recorded as twins.** An earlier draft encoded Owoyemi T and K
as Taylelu and Kehinde, twin brother and sister. That was an inference from two
initials in poster lists, not knowledge. The site lists one Owoyemi, Taiyelolu;
the second row is flagged UNCONFIRMED.

**Needs Andres:** the 62 blank `given_name` rows, and three spelling variants
flagged for confirmation (site `Cheesman` vs authority `Cheeseman`, `Ruschenski`
vs `Ruscheinski`, `Ahsan` vs `Ahssan`).

### 3.5 Motion signature — foreground rule SOLVED, anchor NOT

Spec at `docs/specs/WINK_motion_signature_SPEC_v3.md`. **It is a
reconstruction** — the original v3 never reached this machine — and section 0
states the provenance of every section so it can be diffed against the
original.

**Working foreground rule** (5.4.0), verified against a hand-drawn midline:

```
band   = gaussian(f, 1.0) - gaussian(f, 3.0)
energy = gaussian(|band|, 6.0)
mask   = energy >= percentile(energy, 96.5)
mask   = close(mask, ellipse(31)); drop small components
```

**What is still broken: length.** Width is stable at 35–41 px across five of six
recordings — good evidence magnification does not vary — while length spans
threefold *within* single recordings. Three causes, all confirmed visually:

1. **Fragmentation** when body contrast dips, so the selector takes a fragment.
2. **Coil-bridging** when the animal folds double and the 31 px close bridges
   the limbs of the fold.
3. **A second animal** occasionally in frame, so the selector takes the wrong
   one. Measured at **0.6% of 360 frames** — rare, so this is detect-and-handle
   and **multi-object tracking is not required**.

**No scale may be set until length is fixed.** Implied scale spans 1.10–1.95
um/px and the spread is measurement noise, not magnification.

Development set frozen: `L:\05_Proprioception\pezo-1 CRISPR mutants\`, six
recordings, day 1 adults. **It carries no human pumping scores** — so no
held-out contamination risk, which is what makes it usable — and the "pharynx
known resolvable" property **does not hold for it**, so a pumping failure here
is not diagnostic of the detector.

---

## 4. Open items

**Blocking the motion signature work, in order:**

1. Make per-animal length as stable as width. Link fragments along the body
   axis rather than by isotropic closing, and separate that from whatever
   handles coil-bridging — they need different operations.
2. Add a multi-worm guard (rare, so detect and flag, do not architect around).
3. Explain the food density recording's narrower width (27.6 px vs 35–41),
   which may be the OP50-immersion case.
4. Only then set the scale. **Section 6.1's fractions do not change either
   way** — they are anatomy; only what they resolve to depends on the scale.

**Elsewhere:**

- Which of the six recordings is the OP50-immersed one with no shadow is still
  unidentified. It matters because the foreground rule must not require the
  shadow.
- `L_drive_inventory.csv` **counts immediate files only.** `CRISPR
  mutants_pezo-1_DiI` reports 0 files and actually holds 16 subfolders with
  thousands of TIFs. Grant plan items 0.1 and 0.2 are both planned against that
  inventory and will undercount n.
- Section 4 of the motion signature spec — the frequency census — is specified
  but not built.
- ReagentHub scheduled task still not created (grant plan 0.7).
- `BUILD_APP_UPDATE.ps1` has uncommitted local modifications predating this
  session; left alone deliberately.

**Owned by Andres:** the SMB mount test from the MacBook (grant plan 0.0), and
review of the reconstructed v3 spec against the original.
