# Publishing and deployment: what is actually running, and can it change underneath you

Status: open investigation, blocking the v11.138 release
Raised: 7 August 2026
Prerequisite for: automatic updates to all machines

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
