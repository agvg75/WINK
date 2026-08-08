# Validation against external tools and published data — PLAN v1

Recorded 7 Aug 2026. **New work.** Nothing here displaces the current queue
(scanner wiring, conformance audit, golden records, v11.138).

> **Not to be confused with the reversal-versus-convergence head-to-head**,
> which is unchanged, keeps its name, and is about the detection mechanism
> inside WINK. It has its 30 fps baseline in `41921_cop1367`. This plan is
> about WINK against *other people's* tools and *published* numbers.

---

## V1. Census tagging — rides inside grant-plan 0.1

During the 0.1 header pass, detect other trackers' outputs sitting beside
their source movies:

- `*_features.hdf5`, `*_skeletons.hdf5` — Tierpsy
- WCON files
- any other tracker output found

**Named targets to locate:**

| | dataset | note |
|---|---|---|
| a | Mary's crawling/swimming, wt + dystrophic | **both** the lost-identity set AND its redone labelled version |
| b | the Mars dataset | |
| c | pezo-1 manuscript recordings (Hughes et al. 2022) | **food condition per recording is required** |
| d | affordable-tracker micropublication, with Nick | |

**Output:** a table of movie, tracker outputs, assay, strain-if-known, and
**gaps** — what the papers used that does not survive on any drive. The gaps
column is the one worth the effort; a dataset that is 90% present is a
different object from a complete one, and the difference is invisible until
someone tries to reproduce a figure.

Already measured, as a starting point: `05_Proprioception\pezo-1 CRISPR
mutants` holds 23 folders, **49 FlyCap sessions**, ~260,000 frames across
five strain folders, reconciling with the ~267,000 anchor to within 2.7%.

## V2. Tierpsy results reader

Ingest Tierpsy skeletons and features into WINK's kinematics schema with
provenance `tierpsy_vX`.

**Read, never recompute.** A reader that recalculates is not a reader; it is
a second implementation that will disagree with the first for reasons nobody
tracks.

## V3. Cross-tracker comparison on identical movies

WINK vs Tierpsy; three-way with the affordable tracker where its data allows.

**Identical movies, not merely the same dataset** — different frame subsets
are different experiments. Shared features compared per recording **against
each tool's own within-recording spread**, so "they disagree" is measured
against how much each tool disagrees with itself.

Report **where** they diverge, not only whether. Three trackers agreeing on
an easy recording says little; the informative case is where two agree and
one does not.

## V4. Published-anchor reproductions

The repro corpus gains a **published anchors** tier: DOI, published values as
numeric targets, tolerance **pre-stated from the papers' own reported
spreads**.

**The one-shot rule is the whole discipline.** Run once, report, and do not
iterate against the target.

**Divergence is a finding, never a knob.** It may be a finding about the
pipeline or about the paper; both are worth having, and neither is reached by
tuning. A pipeline adjusted until it reproduces a published number has been
fitted to that number and has stopped being evidence for anything.

Structure implemented in `tools/conformance/rules.py` (`PUBLISHED_ANCHORS`),
seeded deliberately **empty of values** — a placeholder number becomes
indistinguishable from a measured one the moment it is committed, which is
exactly the 0.45 px/um failure.

## V5. Mary's dataset — two halves, strict order

**(i) Prevention, now.** An ingest gate requiring strain and condition to be
declared, or the recording explicitly tagged *unlabeled*. Merges with the
queued `wt`/`control` context rule. Ships with any release.

**(ii) Recovery, later.** A motion-signature classifier proposes labels on the
blind set with a posterior and an **abstain** option, calibrated on the redone
labelled data — **which is thereby SPENT as evidence** and cannot also serve
as validation. Validated by blind separation instead.

Recovered labels are **proposals carrying a travelling caveat, never silent
relabels.**

Waits on the V3 baseline.

**Ask Mary first** whether plate numbers or dates against her notebook can
genuinely unblind any recordings. Real anchors beat an inferred label, and
this question costs one conversation.

## V6. WCON export for WINK kinematics

Standalone. Any time.

## V7. Per-module test-data availability

The question this answers is not "does the tool run" but **"is there anything
in the world we could test it against"** — asked per module, before anyone
schedules validation work that has no data to stand on.

**(a) Each testable module declares its data requirements.** Assay, fps floor,
duration, substrate, single/population. Declared by the module, not inferred
by the query — a module that cannot state what it needs is itself a finding.

**(b) Query the census against those declarations.** Output is a table,
module × one of three columns:

| column | meaning |
|---|---|
| lab data found | paths and n |
| human-scored data found | paths and n; scored data is the scarcer resource |
| nothing found | the gap list |

**Named untested targets: population habituation, paralysis, swim endurance.**
These are named because they are believed untested, not because the query has
run — the query is what settles it.

**(c) For gaps, catalog external candidates.** Record **license and metadata
completeness per candidate**; a dataset whose license or acquisition metadata
is incomplete is not a validation anchor no matter how good the data look.

| candidate | what it offers |
|---|---|
| OpenWorm Movement Database (Zenodo) | WCON + Tierpsy features as **reference answers** |
| BBBC010 | live/dead **ground truth** → the paralysis tool |
| CC-BY micropublication video datasets | e.g. Wormtrails raw videos, DOI-addressed |

**(d) The sorting rule, stated in the spec so it is applied before the data
are seen, not after the result is known:**

- **no ground truth → robustness and refusal testing only.** Does it decline
  what it should decline, and survive what it should survive. No claim about
  measurement accuracy may be drawn from such a dataset.
- **ground truth or published values → measurement validation**, under the
  published-anchor rules of V4.

**YouTube is excluded from validation.** It may serve as refusal-path fixtures
if ever needed, and **degraded repository data is preferred even for that** —
a fixture with provenance beats a fixture without it, including when the
fixture's whole job is to be refused.

**Slots after the navigator.** (b) is runnable the moment V1's census tagging
lands, and need not wait for the rest of V7.

---

## Sequencing

| item | when |
|---|---|
| V1 | rides inside grant-plan 0.1 |
| V2–V4 | September, grant-credit experiments |
| V5(i) | ships with any release |
| V5(ii) | after V3 baseline |
| V6 | any time |
| V7 | after the archive navigator; **(b) unblocks as soon as V1 lands** |
