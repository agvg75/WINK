# September 1 readiness

**Standing artifact. The status section is refreshed every session, so
readiness is a glance and never a reconstruction.**

**Freeze date: 21 August 2026.** On that date, any unfinished Tier 1 item
**executes its fallback without debate**. The fallback is decided now, while
there is no pressure and no sunk cost; a fallback argued about on the 21st is
not a fallback.

---

## Status — updated 8 Aug 2026

| tier | state |
|---|---|
| **Tier 0** | starter copy job specified below, not yet built; account and MacBook not started; first experiment specified, not run |
| **Tier 1** | **6 items enumerated, each with a fallback** (8 Aug). None started. |
| **Tier 2** | not yet enumerated |

**13 days to freeze.** Every Tier 1 item now has a written fallback, and
**none of them can stop 1 September** — which is the useful thing the list
established. What the freeze protects is the *decision*, not the work.

**Cheapest items with the most leverage, if anything is done early:**

- **item 4's partition** — needs a ruling, not work, and it must precede any
  outlining or it cannot happen at all
- **the starter copy job** (Tier 0) — on the critical path in *both* branches
  of item 2, so it is never wasted
- **item 6 before item 2's purchase** — running it after the purchase wastes
  it entirely

---

## Planning principle: VERTICAL SLICES FIRST

**Weeks 1–2 of the window target ONE END-TO-END NUMBER PER CHANNEL, at n = 1**,
**hand-assisted wherever automation is absent.** Hand-assistance is not a
compromise here — the purpose is to find the broken joint, and a human
bridging a gap identifies that gap precisely.

| channel | the one number |
|---|---|
| **pumping** | pump count on **one** recording, against a human score of the same recording |
| **myocyte** | **one** myocyte traced and measured all the way through the extractor path |
| **locomotion** | **one** crawl velocity, against Tierpsy on the **same movie** |

**Horizontal building resumes only after each slice either yields its number
or NAMES ITS BROKEN JOINT.** Not "makes progress" — yields the number, or
says exactly where it stopped and why.

**Why this ordering.** Breadth-first work produces a great deal of
individually-working machinery that has never been asked to produce a result
together, and the joints between stages are where this project's defects have
actually lived: a frame range dropped across a handoff, a derived directory
standing in for a recording, a stale stamp, a modal nobody could click. None
of those were visible in the components. All of them were visible the first
time something was asked to run end to end.

---

## Tier 0 — must exist

### 0.1 Account
### 0.2 MacBook setup

### 0.3 The STARTER data drive

**Named datasets only.** A starter drive that tries to be complete is the
consolidation job again, and it will not be ready.

- pezo-1 **and its conditions**
- the **six frozen** recordings
- **AVG6**
- the **pairing pool** (17 animals)
- **Mary's** sets
- the **affordable-tracker** set
- **Ella's** work
- **hCTM**

### 0.4 One specified first experiment

**Taper derivation + pezo-1 reproduction.** One experiment, specified in
advance. The taper derivation is already owed: it is reference-registry entry
#1, and it retires the standing waiver that currently reads *"believed derived
from measurement (Andrés); derivation not on record."*

---

## FIRST CONCRETE TASK — the starter copy job

**Runnable this week. Independent of grant-plan 0.1**, so it is not waiting on
the census.

**Targets existing hardware.** No purchase is on the critical path.

Requirements, all three learned from the 1.58 TB consolidation:

| requirement | what it prevents |
|---|---|
| **manifest** | a destination that cannot be checked against its source |
| **hashes both sides** | a copy that completed and is wrong |
| **resume** | the first consolidation run minted a new timestamp folder each launch and therefore never resumed; resume is the DEFAULT, not a flag |

And one more, also learned there: **the destination must not poison the
analysis.** Files already copied made their sources look "held elsewhere" and
silently dropped 105,200 files from a manifest. The copy job reads its source
list once, before it writes anything.

---

## Tier 1 — wanted by Sept 1

**On 21 August, every unfinished item below executes its fallback WITHOUT
DEBATE.** The fallbacks are written now, in advance, which is the only time
they can be chosen on their merits rather than against a deadline and a pile
of sunk work.

**Read the fallback column first.** Every one of these is survivable. That is
the point of the exercise: nothing in Tier 1 can stop 1 September, so nothing
in Tier 1 is worth a panic in the last week.

### 1. Grant-plan 0.1 complete
Eligibility, counts per strain, durations.

**Fallback:** publish partial counts **labelled PARTIAL**. Starter-set science
proceeds. The full census becomes a **week-1 credit task**.

### 2. Working-set drive sized, purchased, filled

**Fallback:** the **starter drive** (named datasets, §0.3) on **existing
hardware** — `I:` or the 16 TB — **is the September data plane**. The full set
follows **mid-window, via the same copy tool**. The copy tool is therefore on
the critical path in both branches, which is why it is the first concrete
task.

### 3. Tierpsy results reader (validation plan V2)

**Fallback: defer whole.** It is **itself grant work**, so deferring it costs
nothing that was not going to be done in-window anyway — it becomes a
**week-1/2 Claude Science task on credits**.

### 4. Atlas partition sealed, curation contact sheets confirmed

**Fallback:** **seal the partition on whatever animal list exists at freeze** —
**the partition needs no new work, only a ruling**. Curation **defaults to the
17-animal pairing pool**, with hard cases added later.

This one deserves a note: the partition is cheap and the *timing* is
everything. It must precede any outlining (§4.1 of the atlas spec), so sealing
a slightly worse list on time is strictly better than sealing a better list
late — a late partition is not a partition at all.

### 5. chkdsk H verdict + consolidation manifest verified

**Fallback: none needed for 1 September.** H **stays untrusted and uncleared**
until done. It blocks **drive clearing only, not the start**.

The thing to protect here is the ordering already ruled: if chkdsk is not
clean, **re-walk H and diff against MANIFEST.csv before H is trusted or
cleared**. Nothing about a September start depends on that finishing.

### 6. Zarr read-speed prototype — FIRST RUN DONE (8 Aug 2026)

**Informs drive sizing**, so it wants to land before item 2 is purchased.

`tools/storage/zarr_prototype.py`. First run, on 1,154 uint16 planes
(768×1024, 1,815 MB) from a real recording:

| codec | stored | ratio | read | one plane |
|---|---|---|---|---|
| blosc-zstd-3 | 600 MB | **3.02×** | 401 MB/s | 5.2 ms |
| blosc-lz4-5 | 657 MB | 2.76× | 474 MB/s | 4.2 ms |
| none | 1815 MB | 1.00× | 508 MB/s | 2.4 ms |

**THE DECISION IS DOMINATED BY COMPRESSION, NOT BY READ SPEED.** Compression
costs ~20% of read throughput (401 vs 508 MB/s) — and *every* figure here is
an order of magnitude above the transport this data actually crosses: the
consolidation is sustaining **19 MB/s** over USB, and USB3 tops out around
200 MB/s. **A 401 MB/s decode is never the bottleneck**, so the honest reading
is: compress hard, and buy for the compressed size.

**At 3.02×, 1 TB of this material stores in about 0.33 TB.**

**Two caveats that stop this being a purchase decision on its own:**

1. **One stack.** Compression is content-dependent — confocal background
   compresses far better than dense signal — so the range needs several
   stacks, including a dense confocal one, before a number is trusted.
2. **The box was busy.** The consolidation was running across the same bus,
   so the read rates are lower bounds. Re-run when it finishes.

**Fallback if not completed: skip; buy conventional sizing.** Zarr conversion
becomes an **in-window experiment**.

**Side finding, recorded because it is a data-quality fact and not a Zarr
one:** the test folder holds **two kinds of frame** — 1,154 grayscale
`(768,1024)` planes and **108 RGB `(768,1024,3)`** planes in one recording
directory. The prototype reports the mix and uses the dominant shape rather
than failing with numpy's "all input arrays must have the same shape", which
names neither the count nor the culprit.

**Coupling worth stating: 6 gates the useful version of 2.** If 6 slips, 2's
purchase is made on conventional sizing — which is the fallback, and is fine —
but buying *before* 6 lands wastes 6 entirely. Either run 6 first or accept
the conventional purchase; do not do them in the other order.

---

## Tier 2 — would help

> **NOT YET ENUMERATED.**
