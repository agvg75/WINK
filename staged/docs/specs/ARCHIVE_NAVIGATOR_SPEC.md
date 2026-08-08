# WINK archive navigator — SPEC

Status: draft v1, 7 Aug 2026. **Not started.** Buildable now (see §4.1).
Purpose: one searchable view of the lab's imaging archive — ~10.5 M files
across L, the 16 TB Seagate, I:, and the scope share — so that "do we have X,
where is it, and what state is it in" is a ten-second question instead of a
walk. First consumers: Andrés and students locating recordings; the validation
plan's V1 targets; working-set selection for the MacBook.

Reuse: WINK Hub module (Tkinter tier 0), the correction-log pattern for
labels, the census outputs, the consolidation manifests. Reuse over
reinvention throughout.

---

## 1. Data layer — a catalog, not a live view

1.1 SQLite catalog built from drive walks plus the existing censuses. One row
    per unique item, with a `locations` table since an item may exist on
    several drives.

> **IDENTITY KEY: NAME + SIZE, NOT PATH + SIZE.** See §6 — this is the one
> choice that would make the catalog silently useless.

1.2 Per item: path(s), drive(s), size, mtime, extension, modality class
    (behavioural movie / TIFF sequence / confocal / derived output / other),
    assay guess, strain and condition (§3), person, year,
    tracker-outputs-present flags (Tierpsy signatures, WINK sidecars — V1),
    copy count and single-copy flag, published-anchor membership (pezo-1,
    affordable tracker, Mars), hash where computed.

1.3 **Freshness is explicit.** Every row carries the walk date of its source
    census. The UI shows per-drive census age and warns when stale. The
    navigator NEVER claims to be a live view; re-scan is per drive and
    explicit. Measured properties, not declared ones — the catalog says when
    it last looked.

1.4 Scale: ~10.5 M unique items is well within SQLite. Note the `locations`
    table is larger — the six-location audit found **19.17 M file instances
    against 10.78 M unique identities**, so budget ~19 M location rows.
    Full-text index on paths. The DB lives on L beside the census outputs,
    versioned by build date.

## 2. UI — Hub module, tier 0

2.1 Search and filters: strain, assay, person, year, modality, drive,
    has-tracker-results, single-copy, published-anchor, eligibility (once 0.1
    lands its per-readout flags). Filters compose.

2.2 Results as a folder tree with a flat-list toggle; detail panel per item
    with all fields, locations and census date. Actions: open containing
    folder, copy path. **No move, delete or rename in v1** — the navigator
    reads the archive, it does not operate on it.

2.3 Summary header: counts and TB by drive, modality and label state, so the
    census headline numbers are always one glance away.

## 3. Labels — proposals versus established

3.1 Strain, condition and assay labels come from three sources, ranked:
    **(a) established** — human-confirmed via the ingest gate or this UI;
    **(b) proposed** — parsed from folder and filename conventions, all seven
    date formats and the strain tokens; **(c) unlabeled.** State shown,
    always.

3.2 The **519 unlabelled folders** (96,510 imaging files) ingest as the
    unlabeled backlog. Confirming a label here writes to the same append-only
    correction log the ingest gate uses. Every confirmation is one fewer
    unknown, permanently.

## 4. Build sequencing

4.1 **Buildable now** against the existing full census and confocal census.
    Locations update when the consolidation manifest finalises and when the
    16 TB copy happens. Do not wait for the archive's end state — **the
    navigator is how the end state gets verified.**

4.2 After consolidation completes and chkdsk H rules: ingest `MANIFEST.csv`
    so copy-count and single-copy facts come from **verified hashes** rather
    than walk inference.

4.3 V1 tracker-output tagging lands here as it is built, in the same scan.

## 5. Non-goals for v1

- No file operations beyond open and copy-path.
- No thumbnails (v2 candidate, via the existing contact-sheet code).
- No live watching; explicit re-scan only.
- Not the working-set selector itself — but its filters (eligibility ×
  modality × strain) are exactly how a working set will be chosen, and an
  **export selected list as CSV** action closes that loop.

---

## 6. The identity key, and why path+size fails

The draft said "deduplicated by hash where known, else path+size". **Path plus
size cannot detect a cross-drive copy**, because a copy on another drive has a
different path by definition. Every item would appear unique, `copy_count`
would be 1 everywhere, and the single-copy flag — the field the whole backup
argument rests on — would mark the entire archive as at risk.

**The audits used FILENAME + exact byte count**, which is what found 6.79 TB
held more than once across four locations and 13.78 TB across six. That is the
key the catalog must use.

Its two failure modes are known and must be carried in the spec rather than
discovered later:

- **Under-reports duplicates.** A copy that was RENAMED reads as unique. So
  copy counts are a floor and single-copy is a ceiling.
- **Over-merges.** Two genuinely different files sharing a name and size
  merge into one identity. In an archive of `fc2_save_...-0000.tif` and
  `frame000000.png` this is real — measured, F alone holds 877,676 files under
  505,653 distinct name+size pairs, including 36 recordings whose frames are
  all named identically.

**Therefore: hash where known always wins, and name+size is the fallback with
its uncertainty recorded per row.** A `identity_basis` column ("sha256" or
"name+size") makes the difference visible instead of implied. The
consolidation manifest supplies real SHA-256 for 1.57 M files, which is where
the hashed subset starts.

---

## 7. Queue position, 7 Aug 2026

**Slots after the revert system**, per the sequencing in `ed5bf33`: v11.138 →
publish stages 4+5 → **fix A (analysis context)** → navigator.

**But §4.1 stands and is not a contradiction:** it is buildable against the
existing census immediately, with **no dependency on the consolidation
finishing.** Locations refine as manifests land; they do not gate the build.
The catalog's whole design is that freshness is a per-row property rather
than a precondition.

## 8. chkdsk H — conditional go-ahead recorded

**Runs immediately AFTER the consolidation copy completes**, not before: both
compete for the same USB bus, and the copy has ~8 h left with 0 failures.

**If it does not come back clean:** re-walk H and diff against `MANIFEST.csv`
before H is trusted or cleared.

The reason that diff is the right instrument: the manifest holds a verified
SHA-256 for every file copied off H, so a re-walk that disagrees with it
names exactly which files the filesystem lost or changed. A `chkdsk` result
alone says the volume had errors; the diff says *which of your data* those
errors touched.

**Until then H is not cleared of anything**, and the audit's H figures carry
the caveat that it was walked in `Scan Needed` state — its 2.8 M file count
could be understated.
