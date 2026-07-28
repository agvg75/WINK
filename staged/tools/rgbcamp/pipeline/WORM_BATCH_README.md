# Worm RGBCaMP batch layer & metadata convention

Implements the batch-processing, channel-normalisation, and metadata sections of
`RGBCaMP_fixes_batch_spec.docx`. Two new modules sit on top of the existing
`worm_rgbcamp_analysis.py` (load/QC/dF-F) and `worm_kinetics.py` (kinetics,
including the validated Fix 1 / Fix 2 / sub-resolution flag):

| module | role |
|---|---|
| `worm_channels.py` | configurable channel roles + background normalisation |
| `worm_batch.py` | multi-file assembly, metadata, animal-as-N aggregation, stats |

## 1. Channel configuration & background normalisation (`worm_channels.py`)

`ChannelConfig` assigns each channel a role: `activity` (GCaMP, the Ca readout),
`reference` (Ca-insensitive, for ratiometric motion correction), or `off`.
Default: **green = activity**, red/blue = off.

Fixed, explicit normalisation order:
1. **Background subtraction** — per-frame, per-channel, using an outside-worm
   background column from the extractor (auto-detected among
   `background_mean`, `bg_mean`, …). Produces `<ch>_bgsub`.
2. **dF/F0** on the background-subtracted signal — `<ch>_dff`.
3. **Ratiometric division** by a reference — `<ch>_refdiv` — ONLY if a
   reference channel is designated **and** passes a static-channel guardrail.

**Pilot state:** the current CSVs have no background column, so step 1 is a
no-op and the report flags `background_applied=False`; dF/F0 is then bit-identical
to the old `add_dff` (verified, max|Δ|=0). The subtraction path activates
automatically once the ImageJ plugin exports a background column — no code
change, only data.

**Validated (synthetic background injected):** subtraction lowered the intensity
noise floor 18.6 % and raised dF/F0 amplitude (F0 shrinks once additive
background is removed).

**Reference guardrail:** a channel proposed as `reference` is tested for
calcium-like transients. If it carries transients (e.g. blue mirroring GCaMP),
ratiometric division is **refused** with a warning and the pipeline falls back
to background-subtracted dF/F0. Only a genuinely static reference triggers
`<ch>_refdiv`. This encodes the spec's note that background-normalised GCaMP is
equivalent to mCherry normalisation — a reference is a refinement, not a
requirement.

## 2. Metadata convention (`metadata.csv` manifest, filename fallback)

Grouping is automatic. **Preferred:** a `metadata.csv` (or `manifest.csv`) in the
batch folder — auditable and typo-proof. Columns:

```
filename,genotype,age_day,rnai_target,magnetic_condition,animal_id,quality
```

- `filename` (required) — must match the CSV name exactly.
- `genotype` — `wildtype` | `dystrophic` (free text allowed).
- `age_day` — integer (1, 5, …).
- `rnai_target` — RNAi gene, or `L4440(empty_vector)` for control.
- `magnetic_condition` — `magON` | `magOFF` | `magSHAM` (magnetosensation program).
- `animal_id` — stable unique id; becomes the unit of N. If blank, one is
  synthesised as `recording::worm::hash`.
- `quality` — `good` | `flagged_bad`.

A template is saved as `metadata_manifest_template.csv`.

**Fallback:** when no manifest row exists, metadata is parsed from filename
tokens (`wt`/`n2`→wildtype; `dmd`/`dys-1`→dystrophic; `dayN`/`dN`→age;
`l4440`→control; `magON/OFF`→magnetic condition; `bad`→flagged_bad). Every file's
result — and its source (`manifest` vs `filename`) — is written to the **parse
log** so a mislabel cannot pass silently.

## 3. Batch assembly & the unit-of-N contract (`worm_batch.py`)

`run_batch(csv_dir, cfg)` runs, per file:
`load → QC → channel normalisation → head mask → all kinetics`, then assembles
tidy master tables. Every animal gets a unique `animal_id`.

**Exclusions are explicit, never silent.** Default rules: `quality==flagged_bad`
and recording `duration < 20 s` (length-normalisation floor). Each decision is
in the parse log with its reason.

**Aggregation contract:** metrics are aggregated to the **animal level first**
(per animal × region, median across transients), and group comparisons run
**only across animals** (`animal_level_stats`, Mann-Whitney / Kruskal-Wallis with
rank-biserial). Transients and segments are never pooled as independent
replicates. Sub-resolution decays (Fix-3 flag) are excluded from τ/fall summaries.

**Group-inference guardrail** (`_group_inference_ok`): inference is permitted
only when a grouping axis (genotype, age, RNAi target, or magnetic condition) has
≥2 levels, each backed by ≥2 distinct animals. Otherwise the batch reports
per-recording description only and refuses group statistics. On the 5 pilot files
this correctly refuses (only 2 usable recordings, 1 genotype level).

## 4. Validation (synthetic, worm = unit of N)

8 synthetic worms (4 WT, 4 dystrophic) with a phenotype injected **only** in
decay τ (WT 0.9 s → dystrophic 1.8 s) at equal firing rate. Animal-level
Mann-Whitney recovered the phenotype: decay τ 1.26 → 2.73 s, **p = 0.029**
(rank-biserial −1.0, the floor for 4-vs-4). See `worm_fig_batch_validation.png`.

The same validation surfaces two **detection confounds** the analyst must
control for — both emergent, neither injected:
- **Apparent event rate is undercounted when decay is long** (prolonged decays
  merge adjacent transients; injected rates were equal yet dystrophic reads
  lower). Prefer rate comparisons only within matched decay regimes, or count
  events on a deconvolved trace.
- **Peak dF/F0 inflates under long decay** via transient stacking (residual from
  a prior event lifts the next peak). Amplitude separation here was NOT injected.

## 5. Outputs

`run_batch` returns a `BatchResult`; the driver writes:
`worm_batch_master_transients.csv`, `worm_batch_per_recording.csv`,
`worm_batch_animal_summary.csv`, `worm_batch_parse_log.csv`,
`worm_batch_inclusion.json`. Synthetic validation:
`worm_batch_synth_genotype_stats.csv`, `worm_batch_synth_animal_summary.csv`.

## 6. 8-bit / pixel-unit caveats (unchanged)

`src8bit=1`: absolute intensity is not quantitative — trust dF/F0 and ratios,
not raw resting level. `um_per_px=0`: spatial metrics are in pixels. These are
carried as recording-level warnings.
