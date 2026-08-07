# Drive audit → ReagentHub: migrating folder knowledge into the hub

Status: draft for review
Date: 7 August 2026
Companion to: `tools/drive_audit/propose_labels.py`, `parse_filenames.py`

---

## 1. The destination already exists, and it is empty

ReagentHub v1.9 carries two tables nobody has written to:

```
experiment_folders   0 rows
experiment_shares    0 rows
```

`experiment_folders` has **the exact columns the drive audit produces**:

| ReagentHub column | drive audit source |
|---|---|
| `path` | folder path |
| `nickname` | LABEL_ME `new_name` |
| `person` | proposed, `person_surname_exact` |
| `project` | area / project code |
| `assay` | proposed, `project_token_exact` |
| `strain` | proposed, `strain_exact` or `lab_strain_prefix` |
| `condition` | proposed, `control_exact` / `rnai_gene` |
| `year` | proposed, from folder names **or filename stamps** |
| `n_files`, `imaging_files`, `size_gb`, `holds`, `newest_file` | survey CSV, already measured |
| `notes` | LABEL_ME `note` |
| `status`, `needs_review` | **see section 3** |

This is not a coincidence to be worked around — the landing zone was designed
for exactly this and has been sitting empty. The audit has been generating its
inputs without either end knowing about the other.

---

## 2. What the migration buys

The archive becomes queryable the way strains and plasmids already are:

- every folder a given student touched, across projects and years
- every experiment run in a given strain
- everything from a given year, with the year taken from **acquisition
  timestamps** rather than file mtimes (section 5)
- every RNAi knockdown together with its L4440 control
- every dystrophic-background experiment, by joining `strain` to
  `worm_strains`

That last one is the compounding step. **A folder linked to a strain inherits
its genotype.** AVG6 folders become "dystrophic, body-wall GCaMP2" without
anyone typing it, because `worm_strains` already knows AVG6 is
`dys-1(eg33) I.; Pmyo-3::GCaMP2`. The 101 AVG6 folders stop being 101 separate
facts and become one join.

`experiment_shares` then scopes those views: a student gets one project,
granted and revocable, rather than the whole drive.

---

## 3. A proposal is not a fact, and the schema already knows

`experiment_folders` carries `status` and `needs_review`. **Use them.** A
machine-generated label lands as `needs_review`, and becomes established only
when a person accepts it.

This is the single non-negotiable of the migration. The audit's whole value
rests on the distinction between what was read off a folder name and what
somebody confirmed — and 505 of the 516 person proposals currently rest on a
`given_name` column that was itself assembled from two spreadsheets and a
conversation in one evening.

Migrating unreviewed proposals as established fact would convert a reviewable
suggestion into an unreviewable record, and the drive audit would become a
generator of confident wrong metadata at 551 rows a run.

### 3.1 The evidence has nowhere to go — and this needs deciding

Every proposal currently carries `matched_token`, `matched_in`,
`source_table`, `confidence`, `match_scope`, `evidence_group`, `ambiguity` and
`rule`. **`experiment_folders` has no column for any of it.**

Three options, in order of preference:

1. **A companion table** — `experiment_folder_evidence`, one row per proposed
   field per folder, carrying the tier and the token. Keeps the audit trail
   intact and queryable: *show me every label that rests on a fuzzy match*.
2. **Serialise into `notes`** — cheap, immediately available, and unqueryable.
   Acceptable only as an interim.
3. **Drop it on migration** — do not. The evidence is what makes a label
   arguable, and an unarguable label is indistinguishable from a guess.

Without one of these, a folder in the hub reading `person = Tamrazi M` gives a
reviewer no way to see that it came from an **inherited** match on a parent
folder named `Monica`, shared with 474 sibling folders.

---

## 4. Prerequisites, in order

1. **Enter the six missing strains** (`reagenthub_missing_strains.csv`):
   COP1367, COP1553, AG405, AG406, AVG6, VG02. 371 GB and 235,000 files of
   data currently point at strains the hub does not have, and until they exist
   the `strain` column cannot be a foreign key to anything. This also promotes
   106 proposals from `lab_strain_prefix` to `strain_exact`.
2. **Fill `Projects.strains`** on the authority file — blank for all 19 lines.
   It lets a strain identify a project and a project disambiguate a person.
3. **Review the proposals.** 21 distinct person facts cover 516 folders, so
   the review is far smaller than the row count suggests — `evidence_group`
   means accepting one `\Monica` decision accepts 475 folders.
4. **Decide 3.1** before the first write, not after.
5. **Then migrate**, `needs_review` set, in one transaction, with a backup
   taken first. `L:\ReagentHub\backups\` already holds dated copies.

---

## 5. Year: take it from acquisition stamps, not mtimes

`parse_filenames.py` reads 615,951 filenames in 17 seconds and recovers an
acquisition year for **655 folders**, of which **619 had no year from their
folder name at all** — against 181 from folder names, roughly a fourfold
improvement.

**Where the filename stamp and the file mtime disagree, prefer the stamp.** An
mtime records when a file was last written, so copying an archive rewrites
every one of them; the filename keeps the day the animal was filmed. Measured:
75 of 655 folders disagree, almost always with the mtime *later*, which is the
signature of a copy.

> **Caveat that must be resolved before this is trusted.** Gaps of +1 to +4
> years (53 folders) are credible copy drift. The tail — +14, +21, +25 years —
> is more likely the year regex matching a sequence number such as `2001` in
> `img_2001` than real drift. Verify the outliers before migrating any year
> derived this way, and treat the fourfold coverage claim as resting on the
> credible band only.

---

## 6. What must NOT happen

- **No write to the live database without an explicit human action.** Every
  query in this work so far has been read-only, by URI, and that is the
  default the migration inherits.
- **No unreviewed proposal stored as established.** See section 3.
- **No dropping of evidence on migration.** See section 3.1.
- **No inferring a person from a folder name alone where the name is
  ambiguous.** `\Erin\` resolves to Cheeseman or Sawilchik only when a year or
  project says which; without one, both are recorded and neither is chosen.
- **No back-filling `worm_strains` from folder names.** The drive says `AVG6`
  exists; it does not say what AVG6 *is*. Genotypes come from the bench, and
  the six candidate entries are marked with what still needs confirming.
