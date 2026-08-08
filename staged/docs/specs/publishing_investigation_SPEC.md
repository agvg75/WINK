# Publishing and deployment: what is actually running, and can it change underneath you

Status: open investigation, blocking the v11.138 release
Raised: 7 August 2026
Prerequisite for: automatic updates to all machines

---

## 0. The version number means one thing (Andrés, 8 Aug 2026)

**MAJOR.COUNTER.** `11.139` is the **139th release of the v11 line**, not a
decimal — the counter is **unbounded and semantically meaningless beyond
ordering**. 11.9 precedes 11.10 precedes 11.139, and nothing else should be
read into the digits.

**The major increments ONLY on a compatibility break:**

- **sidecar or schema changes old tools cannot read even with migration**, or
- **changes that invalidate cross-version measurement comparability, or
  invalidate pins.**

**Feature size never justifies a major bump.** A release can add an entire new
tool family and stay on v11; that is the normal case, not an exception.

**We stay on v11 indefinitely. v12 is a deliberate, rare, announced event.**

**Why it is written down rather than inherited:** an unstated convention gets
re-derived by the next person from the digits in front of them, and the
obvious reading of "11.139" is a decimal that ought to roll over into 12
eventually. It does not. Under the revert system a major bump is also the one
version change that can break a student's pin, which is precisely why it
belongs to compatibility and not to how much work went in.

Stated again in `tools/publish/publish_release.py`, beside the command that
applies it.

---

## Why this is its own investigation and not a release step

Andrés's stated publishing philosophy is to push updates to everyone
automatically and find out what broke, rather than maintain ten versions in
the wild — because unreproducible bug reports are worse than one bad release.
That is a sound position, and it has two prerequisites:

1. **The updater must fail loudly.** If it can deliver an incomplete build
   silently, automatic updates spread incompleteness faster than manual ones.
2. **What is deployed must be visible.** Otherwise a fleet-wide push is a
   change you cannot audit.

Neither holds today. Until they do, cutting v11.138 is a gamble rather than a
routine act.

---

## 1. The Hub can migrate a running session to a different tree, silently

**This is the most serious item and it was found by accident**, while checking
whether the GCaMP tool could spawn a subprocess from the published copy.

`app/lab_hub.py` line 877:

```python
redirect = self.updater.apply(manifest)
...
if redirect is not None:
    messagebox.showinfo("Opening published WINK update", ...)
    subprocess.Popen([sys.executable, str(redirect / "app" / "lab_hub.py")],
                     cwd=str(redirect / "app"))
    self.after(200, self.destroy)
```

A Hub started from one tree can **relaunch itself from another** and destroy
the original. Every tool spawned afterwards inherits the new root, because
each derives `ROOT` from its own `__file__`.

**The consequence is not merely that you cannot see what is installed. It is
that what is running can change mid-session.** A person who launched a
staged build to test a fix can, after accepting one dialog, be running the
published build while believing otherwise — and every conclusion drawn after
that point is about the wrong code.

### 1.1 The version string does not reveal it

Measured 7 Aug 2026: a Hub launched entirely from `staged\app\lab_hub.py`
displays **`WINK v11.137`** in its title bar, because the string is not
derived from the tree in use. So the one indicator a person would check is
the one that cannot detect the problem.

### 1.2 What it needs

- **The version string must reflect the tree actually running.** Derived at
  runtime from the location of the loaded module, not from a constant.
- **The redirect must be visible rather than silent.** A dialog that appears
  once and is dismissed is not a record. At minimum the destination tree must
  be shown before the switch and remain visible afterwards.

---

## 2. Did v11.127–v11.133 publish incomplete?

51 files were reported missing from a published build. Unresolved:

- Did those releases ship incomplete to students?
- How did the 51 come to be missing?
- **Can the mechanism produce a partial publish without saying so?**

The third question governs the other two. If a silent partial publish is
possible, v11.138 can go out broken the same way and nobody would know —
and under automatic updates it would reach every machine before anyone
noticed.

**If the mechanism is sound and 11.133 was a one-off, cutting v11.138 is
routine. If it can silently truncate, that is fixed before anything ships.**

Acceptance: a publish either completes verifiably or fails loudly. A
manifest with a file count and a per-file check, refusing to mark a release
current unless every file arrived.

---

## 3. Deployment visibility

Minimal and sufficient: **the Hub writes its version, the tree it is running
from, the machine name and a timestamp to a file on the L drive at launch.**

That converts an assumption into a fact, and would surface:

- machines still on 11.124 that are off-network at update time
- sessions that migrated tree mid-run (item 1), since the recorded tree would
  disagree with the version
- whether an automatic push actually reached everything

The tree must be recorded alongside the version. Recording the version alone
reproduces the blind spot in 1.1.

---

## 4. Order

1. **Item 1**, because it invalidates testing. Neither Andrés nor a student
   can trust an observation while the running tree can change underneath it.
2. **Item 2**, because it gates the release.
3. **Item 3**, which is small and makes 1 and 2 auditable afterwards.

Only then: v11.138, and only then automatic updates.

---

## 4.1 Exhibit 1: RESOLVED, 7 Aug 2026

`BUILD_APP_UPDATE.ps1` was found modified and uncommitted, blocking the first
publish. Forensics, one command each:

| | |
|---|---|
| file last modified | **6 Aug 2026, 15:19:46** |
| v11.137 commit `f74c93c` | **6 Aug 2026, 15:20:20** |
| gap | **34 seconds** |

Same keystroke session: the changelog was written, the code commit went out
34 seconds later, and the changelog edit was never staged.

And no release commit had touched the file for three consecutive releases:

| commit | release | touched it? |
|---|---|---|
| `ce81381` | v11.135 | no |
| `2944c9f` | v11.136 | no |
| `f74c93c` | v11.137 | no |
| `abda827` | v11.134 | yes — the last one |

Which is why the recovered edit is *cumulative*: three entries written at
once at 11.137 time, catching up three releases of stranded documentation.

**The finding is worse than the one this investigation opened with.** The
original question was whether the publish mechanism could silently truncate.
The answer is that it had **no relationship to the commit at all** — it was a
separate script, run separately, whose output drifted from what shipped and
whose drift nothing could detect. Release notes for three releases existed
only in one person's working tree.

**Class closed.** `publish_release.py` refuses a dirty tree, so a release
whose documentation is uncommitted cannot be published. The failure that
stranded three changelogs is now impossible rather than merely unlikely.

## 5. What is already known

- 40 commits since v11.137; 13 touch code students run.
- No hardcoded published paths exist in `app/` or `tools/` — every tool
  derives `ROOT` from `__file__`. The redirect in item 1 is the sole path by
  which a session changes tree.
- The process-path check is currently the only reliable way to tell staged
  from published:

  ```
  Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "lab_hub" }
  ```

  Requiring a WMI query to answer "what am I running" is itself the finding.

---

## 6. Roadmap after v11.138 — SEQUENCING DECISION, 7 Aug 2026

**Publish stages 4 and 5 are the FIRST items after v11.138 ships**, ahead of
the validation plan and the reference registry.

**Rationale, and it is the right one: revert is the safety net that makes
continuous release cheap.** The whole publishing philosophy is to push to
everyone and find out what broke, because unreproducible bug reports are
worse than one bad release. That trade only holds if a student can get off a
bad version in thirty seconds. **The net must exist before the cadence
speeds up**, not after the first bad release proves it was needed.

**Target: shipped by 11.139 or 11.140**, so the picker has real launch
history to offer by the third release. A version picker with no history is a
list of numbers.

### 6.1 Stage 4 — per-module effective versions

**Effective version = the last published version whose tree changed that
module's files.** Module-to-file mapping is declared; shared and core files
count as touching every module.

Each tool displays its effective version in-app. Clicking it lists **only the
versions where that module actually differed**, with date and a one-line
change note — a list of every release would be noise, and the point is to
show the versions that could possibly have changed this tool's behaviour.

Selecting one relaunches from **that version's WHOLE TREE**. Never mix module
files across trees: a module from one release running against core files from
another is a configuration nobody has ever tested and nobody could reproduce.

Old code must **fail loudly** on newer sidecar and schema versions — schema
version checked on load, never assumed. The existing
`load_tracker_session` frame-count check is the pattern.

### 6.2 Stage 5 — per-user history and revert

Every tool launch appends **(user, module, effective version, machine,
timestamp, outcome)** to that user's settings. Outcome is `clean-exit` or
`crash`, taken from the crash handler already shipping in published trees.

The picker annotates each version from **that user's own history**: current /
last used by you and when / last clean session / never used by you.

**"Revert" defaults to the most recent version with a CLEAN session for this
user** — not merely the previous number. The previous number may be one they
never ran, or one that crashed on their machine. The last version that
actually worked *for them* is the useful default.

**Pins are per user, per tool.** One student pinning a tool affects nobody
else, which is what makes reverting cheap enough to do without asking.

**Effective version and pin state go into the version string, every crash log
entry, and every exported CSV and sidecar** — so a result can always name the
code that produced it, per the invariant in section 1.
