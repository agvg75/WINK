# Worm RGBCaMP kinetics & comparison layer (`worm_kinetics.py`)

Builds on `worm_rgbcamp_analysis.py` (load → QC → dF/F₀). Adds the kinetics and
comparison analyses for the DMD program. Every function operates on the reliable
body only — the head mask is applied first.

## Head mask (your spec)
Myocytes 1–8 sit over the pharyngeal mCherry and a head GFP neuron, so **red and
green are unreliable in segments 0–7**. `mask_head()` NaNs green + red (and every
derived `_dff` / `_dF_dt` and the RG/GB/RB ratios) inside those segments while
**keeping blue** (ER indicator). Muscle *i* (1-based) ≈ segment *i*−1 (0-based
plugin index), so "myocytes 1–8" → segments 0–7. All kinetics run on the
reliable body, split at its midpoint: **anterior = segments 8–15, posterior =
16–23**.

## Metadata from filename (your spec)
`parse_metadata()` reads genotype / age / RNAi target from the file **name**
(the CSV stores only the magnetic condition). Token grammar (case-insensitive):

| axis | tokens | →|
|------|--------|---|
| genotype | `wt`,`n2` / `dmd`,`dys1`,`dys-1`,`dystrophic` | wildtype / dystrophic |
| age | `day1`/`d1` … `day5`/`d5` | integer day |
| RNAi | `l4440` / any other lead token | empty-vector control / target |
| quality | `bad`,`bad2` | flagged_bad |

Example names that parse cleanly:
`WT_day1_l4440_1G.csv`, `dmd_day5_unc22_1G.csv`, `dys1_day1_ctrl_bad.csv`.
Unspecified axes return `None`, so grouping code skips them. **The five pilot
files don't encode genotype/age yet** — name future recordings this way and the
grouping is automatic.

## Analyses (one function each)
| function | question | key outputs |
|----------|----------|-------------|
| `region_split` | anterior vs posterior | mean, p95 dF/F₀, active fraction per worm×region |
| `contraction_state` | contracted vs relaxed | Δ calcium in top vs bottom curvature tercile, rank-biserial, p |
| `release_reuptake` | release vs reuptake | per-transient rise time (release), decay τ (reuptake), τ/rise ratio |
| `intersignal_timing` | timing between Ca channels | plugin `lag_*_ms` + cross-corr lag between channel dF/F₀ |
| `amplitude_coupling` | contraction amp vs Ca | corr(\|seg_angle\|, Ca) + lag (Ca leads bend if +) |
| `movement_coupling` | displacement vs Ca | corr(\|axial velocity\|, body Ca) + lag |
| `wave_propagation` | A→P wave kinetics | phase-gradient wave speed, direction, coherence, undulation freq |
| `cycle_average` | mean contractile cycle | phase-locked dF/F₀ waveform per region, period, Ca peak phase |

## Wave propagation — why phase-gradient, not pairwise lag
At ~5 Hz with ~0.1–0.16 Hz undulation there are only ~5 frames per bend cycle, so
adjacent-segment propagation delays fall **below one frame**; naïve
segment-to-segment cross-correlation quantises to zero and mislabels a clear
traveling wave as "standing." `wave_propagation()` instead band-passes the
kymograph around the undulation frequency, takes the Hilbert analytic phase per
segment, and fits **phase vs body position** each frame. The phase slope +
frequency give speed (segments/s), the slope sign gives direction, and the
fraction of well-fit frames is a **coherence** score (0–1). Report speed only
when coherence is meaningful (≳0.5); low coherence means the pattern isn't
wave-organized in that clip.

## Kinetics caveats baked in
- **Decay-τ fits pinned at the 20 s bound are rejected** (incomplete decay within
  the 6 s window) — they are not real reuptake constants.
- 8-bit source: kinetics use dF/F₀ and ratios (robust), never absolute levels.
- `self_approach_flag` is not a whole-frame reject; treat curvature-dependent
  metrics (contraction_state, amplitude_coupling) as caveated when it fires often.

## Quick start
```python
import worm_rgbcamp_analysis as wa, worm_kinetics as wk
r = wa.analyse_recording("WT_day1_l4440_1G.csv")   # load→QC→dF/F0
m = wk.mask_head(r.df)                              # NaN red+green in seg 0-7
wk.region_split(m)                                  # ant vs post
wk.release_reuptake(m, "w1")                        # release/reuptake per transient
wk.wave_propagation(m, "w1")                        # A→P wave speed + coherence
wk.cycle_average(m, "w1", region="posterior")       # mean contractile cycle
```
Batch (writes all kinetics tables): `python run_worm_analysis.py csv_dir out_dir`

## Not yet in the data
- **Age (day1/day5)** and **explicit WT/dystrophic labels** aren't in the five
  pilot files — encode them in filenames (above) and grouping is automatic.
- With single-worm recordings, cross-genotype/age statistics need N animals per
  group; `condition_stats` (in the core module) is ready and uses the worm as the
  unit of N. Until then, output is per-recording description.
