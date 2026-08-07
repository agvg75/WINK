# Confocal census — what exists, what shape it is, where it lives

Grant plan item 0.2. Run 7 August 2026.
Tools: `tools/confocal_census/find_confocal.py`, `confocal_census.py`
Data: `tools/confocal_census/confocal_census_2026-08-07.csv` (9,872 rows)

---

## 1. The headline is not the count, it is where the data is

| storage | confocal files | size | **exists nowhere else** |
|---|---|---|---|
| `L:\` (lab drive) | 1,404 | 942.2 GB | 1,312 files — **558.9 GB** |
| `\\SLB122E-01\Vidal-Gadea_lab` (scope PC) | 389 | 1,711.6 GB | 312 files — **1,359.4 GB** |

**The scope computer holds nearly twice as much confocal data as the lab drive,
and 1.36 TB of it is on that machine only.** It is a microscope control PC in
SLB 122E — a workstation under a scope, not a backed-up server. Every stack in
that 1.36 TB is one disk failure from not existing.

Only 77 of the scope's 389 files have a counterpart on L. This is not a
metadata problem, and it is not something the migration fixes; it is the
single most consequential thing this census found, and it was found by
accident, because the census was pointed at the L drive alone until the
scope share came up mid-run.

Matching is by filename **and** exact byte count, so it under-reports rather
than over-reports: a file copied and renamed reads as two files, and is
counted as unbacked on both sides.

---

## 2. What was acquired

648 `.lif` files opened, **8,446 acquisition series**, in 57 seconds.

| shape | series | z planes |
|---|---|---|
| z-stack | **5,190** | 277,356 |
| single plane | 2,965 | 2,965 |
| timelapse | 291 | 291 |

Stacks run 2 to 1,240 planes, **median 37**. Median z step **0.355 µm** over a
median depth of 18.5 µm, with z:xy anisotropy of 3.3× (p90 4.9×) — ordinary,
well-sampled confocal geometry.

**1,426 series were excluded as derived**, and this matters for any count
quoted from here:

- **767 LIGHTNING deconvolutions** (`Series001_Lng`) — Leica stores the
  deconvolved result as a sibling series in the same file. It is the *same
  recording* as its parent.
- **659 FLIM analysis products** — `Fast Flim`, `Standard Deviation`,
  `FlimDecayTime`, `Pattern Matching Scatter Plot`. Not recordings at all.

One series in six is one of these. The first run of this census reported 3,564
z-stacks on the scope computer; the true figure is 3,077.

---

## 3. Can anything be measured from them

**91.8% carry spatial calibration** (7,754 of 8,446). µm/px runs 0.0078 to
25.83, median 0.180.

The 8.2% without it are mostly the uncalibrated derived planes and a tail of
older acquisitions. A stack without µm/px can still be counted and looked at;
it cannot contribute a distance, a volume, or a neurite length.

---

## 4. How much of it could be head stacks

**A `.lif` header contains no anatomy.** Nothing in the file says "head", so
this census does not claim one. The closest a header gets is field of view,
and that narrows it usefully:

| field of view | acquisition z-stacks |
|---|---|
| < 100 µm | 449 |
| **100–250 µm** | **3,149** |
| 250–500 µm | 590 |
| 500–1,000 µm | 462 |
| > 1,000 µm | 540 |

An adult worm is ~1 mm long and ~65 µm across; the pharynx is ~150 µm. So the
**3,598 stacks under 250 µm are the head-and-neighbourhood-sized ones**, and
the 540 above 1 mm are whole animals. By strain, the sub-250 µm stacks are
AVG60 (726), AVG57 (227), N2 (214), VG03 (159), AVG63 (112).

That is the number to take into §5.3: **on the order of 3,600 candidate stacks
already acquired**, not the handful the plan assumed. Which of them are heads
is a human judgement and stays one.

---

## 5. Caveats, so nothing here is read as firmer than it is

- **`.lsm`, `.czi` and `.nd2` were counted but not opened** — 1,143 files,
  41 GB, most of it 1,078 Zeiss `.lsm`. No reader for these exists in this
  codebase and guessing at their headers would be worse than reporting them
  unread. The 8,446 series figure therefore covers Leica only.
- **Confocal data exported as TIFF is invisible to this census.** At least one
  such export exists on L (`06.11.25 CONFOCAL_AVG77 ... _t001_ch03_SV.tif`),
  so the true confocal footprint is larger than 942 GB on the L drive.
- **The 2008 row is one ambiguous filename**, not a year. All 63 series come
  from `081021_Nmgp-1-GFP in OH15500.lif` (held in three places). Under the
  lab's YYMMDD convention that reads 21 Oct 2008 — before this lab existed —
  so it is far more likely October 2021 written another way. Do not treat any
  pre-2019 year from this census as real without opening the file.
- **Two files could not be read**, both under `\Aalimah\`:
  `Aalmah  Earth gen 2.lif` and `Project.lif` — a `.lif` marker but no image
  series. Possibly truncated, possibly project-container files.
- **3,935 series have no year in their path** and 4,472 no strain. The
  filename-stamp pass (`parse_filenames.py`) would recover much of the year;
  it has not been pointed at these paths yet.

---

## 6. What this changes

1. **Back up the scope computer.** 1.36 TB, single copy, on a workstation.
   This is now the top operational item and it outranks everything in the
   metadata backlog.
2. **§5.3 branches on ~3,600 candidate stacks**, with calibration on 92% of
   them, spanning 2019–2025 and concentrated in AVG60, AVG57, N2 and VG03.
   The September decision has data under it.
3. **The scope share is organised by person**, and those folder names resolve
   against the same authority the drive audit uses — 5,112 of 5,206 series got
   a person. It should be swept into `experiment_folders` alongside L, with
   `source` kept as a column, not merged.
4. **The geometry supports volumetric work.** 0.355 µm z steps at 3.3×
   anisotropy is not a limitation to design around.
