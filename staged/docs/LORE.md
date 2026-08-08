# Lore

Cross-cutting invariants learned from incidents in this project.

**Why this file exists separately from the scanner.** `tools/conformance/
rules.py` holds the invariants a machine can check, each with its incident.
These are the ones a machine cannot check but a person can hold in mind. They
earn their place by having been paid for.

---

## One fact, one rendering path

**State shown anywhere a person DECIDES must render through exactly one
path.**

**The incident, 8 Aug 2026.** The egg counter stored a per-egg `review_state`
and drew it twice: the interactive scatter read the state raw, the overlay
writer lowercased it first. The same egg could appear **cyan (unreviewed) on
screen and green (accepted) in the saved overlay** — one fact, two renderings,
and the screen was the wrong one.

**Why it matters more than a colour bug.** The screen is where the person
decides. A rendering divergence at that point does not merely display
something wrong; it **changes the decision that becomes the data**. The egg
counts are a measured value, and they are produced by a human looking at
colours.

### This is the human-layer form of the tier invariant

The tier invariant, from `docs/specs/bodywall_flattening_SPEC.md` §6.2:

> **higher tiers may smooth the interaction and must never change the
> values.** A value that depends on which tier the student was running is a
> defect.

That governs the machine layer — rendering quality must not reach the numbers.
**The human-layer form governs the reverse direction**: when a person's
judgement IS an input, the rendering they judge from is part of the
measurement path, and two renderings of one fact are two measurement paths.

**So: divergence is a defect even when both renderings are "just display."**
Especially then — because nothing downstream will ever disagree, and the
error enters as a human choice that looks exactly like a considered one.

**Test for it the same way:** render both, compare, and require them equal.
Not "both look reasonable."

---

## Error machinery must be fired to be trusted

Recorded as a scanner family (`handler-name-bound-in-try`,
`enum-dispatch-no-raise`) because two of its forms are statically checkable.
The general statement belongs here.

**A handler, a refusal, or a fallback that has never run is not known to
work — it is known to compile.** Four instances, three of them written by
Claude and caught by reading rather than by running:

| | |
|---|---|
| a crash handler | filed a **clean exit** moments after reporting the crash, because `atexit` runs after it |
| a publish refusal | printed a failure notice reading **`PASS`**, quoting stdout while the traceback sat on stderr |
| an `except ContextError` | named something imported **inside the try it guarded** |
| the scanner's own self-test | was silenced by the fixture exclusion — 9 of 9 rules went to 0 of 9 and it reported success either way |

Each is only entered on the failure path, which is where nobody looks until a
student gets there.

---

## Minutes of use beat suites of checks, at the surface

**v11.139 shipped with 168 passing checks. One minute of real use found a
defect none of them covered, and a worse silent one behind it.**

Not an argument against tests — the suite is why the logic is trustworthy.
An argument about *where* confidence is thin: GUI behaviour is verified
through non-Tk cores precisely **because** Tk is hard to assert about, which
puts the thinnest coverage exactly where a person's hand goes.

Standing requirement in `docs/specs/publishing_investigation_SPEC.md` §0.0.
