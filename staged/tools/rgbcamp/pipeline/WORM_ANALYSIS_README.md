# Worm RGBCaMP downstream analysis

A QC-aware Python analysis layer for the **per-segment CSVs exported by
`WormRGBCaMPMap_v1.java`**. The ImageJ plugin does the hard extraction (tracks a
freely-moving worm on DIC, fits an eigenworm-constrained midline, cuts 24
hemisegments/side, reads blue/green/red per segment, measures curvature +
kinematics). It intentionally stops at raw extraction. This layer adds the
normalization, aggregation, kymographs, curvature–calcium coupling, and
condition statistics — everything from the CSV to a figure.

## Files
| File | Purpose |
|------|---------|
| `worm_rgbcamp_analysis.py` | Analysis library (load → QC → dF/F₀ → summary → kymograph → coupling → stats) |
| `run_worm_analysis.py` | Batch a folder of extraction CSVs → per-recording + cross-recording tables |

## Channel roles (from the plugin header)
- **green = cytoplasmic GCaMP** → primary body-wall muscle calcium readout
- **red = mito RCaMP / pharynx mCherry**
- **blue = ER indicator**
- ratios `ratio_RG`, `ratio_GB`, `ratio_RB` and their time-derivatives are exported per segment

## Two data-integrity facts these files forced (read before interpreting)

1. **All supplied recordings are 8-bit (`src8bit=1`).** The plugin's own note:
   on 8-bit (mp4) sources absolute intensities are *not* fully quantitative, but
   **ratios and dF/F₀ are robust**. So the pipeline does **not** blank
   intensities — it flags the recording and steers you to relative readouts.
   Raw resting-level comparisons across genotypes carry this caveat; ratiometric
   resting (`median_ratio_*`) is the safer resting proxy.
2. **The RNAi/genotype label is in the FILENAME, not the CSV.** Each CSV is one
   worm; the CSV `condition` column holds the magnetic condition (`1G`).
   `L4440` = empty-vector RNAi control. `genotype_from_filename()` parses this;
   edit it for your naming scheme.

Additional automatic flags raised per recording:
- **Anterior saturation.** Segments 0–4 (head/pharynx region) hit the 8-bit
  ceiling in every recording (up to ~86% of frames at segment 0). `qc_report
  ['saturated_segments']` lists them; drop or caveat head-region intensity
  metrics.
- **`um_per_px=0`** → spatial metrics are in pixels, not microns.
- **Single worm per file** → not a unit-of-inference sample. Aggregate multiple
  recordings per genotype before running `condition_stats`.

## QC policy
`QCPolicy` rejects frames flagged `coil/area/size/len_short/partial/low_evidence`
and `found==0`/`skip==1`, and frames leaking signal outside the body
(`fluor_outside_frac` > 0.25). **`self_approach_flag` is deliberately not a
whole-frame reject** — it flags curvature-shortcut risk (posture), not
photometry, and fires on 50%+ of freely-moving frames; treat it as a caveat for
curvature-dependent metrics only.

## Quick start
```python
import worm_rgbcamp_analysis as wa

r = wa.analyse_recording("WormRGBCaMP_extracted_yes.csv")
print(r.warnings)                 # data-integrity notes
print(r.qc_report["retention_frac"], r.qc_report["saturated_segments"])
r.worm_summary          # per-worm DMD-relevant readouts
r.coupling              # per-segment curvature–calcium correlation + lag

# anterior→posterior calcium wave map
M, seg_axis, time_axis = wa.kymograph(r.df, "w1", value="green_dff")
```

Batch a folder:
```bash
python run_worm_analysis.py  path/to/csvs  output_dir
```

## Metrics produced
**Per worm × segment** (`per_worm_summary`): `resting_<ch>` (raw, caveated on
8-bit), `dff_p95_<ch>` (transient magnitude), `active_frac_<ch>`,
`median_ratio_*` (8-bit-robust resting proxy), `mean_abs_curv`,
`curv_calcium_r` (within-worm coupling).

**Curvature–calcium coupling** (`curvature_coupling`): per-segment zero-lag
correlation and best cross-correlation lag between |curvature| and green dF/F₀.
A lag ≠ 0 means muscle activation leads/trails bending; a coupling that weakens
in dystrophic muscle is a candidate phenotype.

**Condition statistics** (`condition_stats`): Mann–Whitney U with rank-biserial
effect size, Hodges–Lehmann median difference, and Benjamini–Hochberg FDR —
**with the worm as the unit of N** (per the analysis brief's nested design).

## Statistical design (per your brief)
Transients ⊂ ROIs/segments ⊂ animals ⊂ condition ⊂ model. The animal is the
primary unit of inference. `condition_stats` operates on per-worm summaries, so
one worm contributes one value per metric — never per-segment pseudoreplication.
For the full nested design across many animals and RNAi targets, a
linear-mixed-model layer (`animal` random intercept, `genotype` fixed effect)
is the next addition; with the 5 single-worm recordings here, per-recording
description is the honest ceiling.
Every new extraction also saves `<recording>_review_rois.zip` beside the CSV. Open it in ImageJ's ROI Manager while the original stack is open to restore the exact accepted body outline and head-to-tail midline for every analyzed frame. Filling a saved body polygon recreates the binary mask without storing a multi-gigabyte 4K mask TIFF. Legacy CSV files alone cannot reconstruct an exact mask because they do not contain absolute boundary or midline coordinates.
