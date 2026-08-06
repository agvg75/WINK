"""Rename experiment folders from a spreadsheet, reversibly, with a ledger.

Andres: he will go through the drive inventory assigning meaningful names, then
hand the sheet back to be applied - with old and new names linked and
remembered, so a rename can be undone and a file can still be found from its
original path.

THE LEDGER IS THE POINT, NOT THE RENAME. Renaming is one call. What makes it
safe to do to a decade of research data is that every rename is recorded before
it happens, verified after, and reversible from the record alone. A rename
without a ledger is indistinguishable from data loss to anyone who had a path
written down.

WHAT RENAMING A FOLDER BREAKS, and it is worth being blunt because it is not
obvious: every absolute path stored anywhere inside or about that folder stops
resolving. Analysis CSVs that record their source, geometry sidecars, Fiji
scripts, figure captions, a student's notebook, a path pasted into a manuscript
- none of them are updated by renaming, and none of them fail loudly. They fail
by not finding a file. `resolve()` exists so an old path can still be turned
into a current one years later, which is the only reason this is safe to do at
scale.

DRY RUN IS THE DEFAULT. `apply()` does nothing unless explicitly told to, and
reports exactly what it would do. Every check that can be run without touching
the disk is run first, because finding the collision after renaming 300 folders
is a much worse afternoon than finding it before.

WINDOWS SPECIFICS THAT BITE HERE:
  - MAX_PATH is 260 characters. A longer, more meaningful name can push files
    DEEP inside a folder past the limit, and those files then cannot be opened
    by ordinary tools even though the rename appeared to work.
  - Renames are case-insensitive but case-preserving, so "worm 4" -> "Worm 4"
    is a real change that a naive collision check calls a conflict.
  - A folder open in Explorer, or a file open in Fiji, refuses to be renamed.
    That is a transient failure and should be retried, not recorded as refused.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
from pathlib import Path

MAX_PATH = 260
ILLEGAL = set('<>:"/\\|?*')
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
    | {f"LPT{i}" for i in range(1, 10)}


class RenameError(Exception):
    """Refusals that name the consequence."""


def _who():
    try:
        import operator_identity
        return operator_identity.initials() or None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def read_plan(csv_path, *, old_col="path", new_col="new_name"):
    """Read the spreadsheet. Blank new names mean 'leave this one alone'.

    A blank is the common case - most rows will not be renamed - so it must be
    the quiet one. An error on every unfilled row would make a 1200-row sheet
    unusable.
    """
    rows = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if old_col not in (reader.fieldnames or []):
            raise RenameError(
                f"No {old_col!r} column in {csv_path}. Without the original "
                f"path there is nothing to rename, and guessing from the "
                f"folder name alone would match the wrong folder wherever a "
                f"name repeats - which on this drive it does.")
        for i, row in enumerate(reader, start=2):
            new = (row.get(new_col) or "").strip()
            if not new:
                continue
            rows.append({"row": i, "old_path": row[old_col].strip(),
                         "new_name": new,
                         "note": (row.get("note") or "").strip()})
    return rows


def check_plan(plan, *, deepest_child_len=None):
    """Everything that can be checked without touching the disk, checked first.

    Returns (ok, problems). Finding a collision after renaming 300 folders is
    a much worse afternoon than finding it before.
    """
    problems, seen_targets = [], {}
    for item in plan:
        old = Path(item["old_path"])
        new_name = item["new_name"]
        where = f"row {item['row']}"

        bad = sorted(set(new_name) & ILLEGAL)
        if bad:
            problems.append({
                "row": item["row"], "kind": "illegal_characters",
                "detail": f"{new_name!r} contains {''.join(bad)}",
                "why": "Windows will refuse the rename outright."})
            continue
        if new_name.upper().split(".")[0] in RESERVED:
            problems.append({
                "row": item["row"], "kind": "reserved_name",
                "detail": f"{new_name!r} is a reserved device name",
                "why": "Windows cannot create a folder with this name."})
            continue
        if new_name != new_name.strip(" .") or not new_name:
            problems.append({
                "row": item["row"], "kind": "trailing_space_or_dot",
                "detail": repr(new_name),
                "why": ("Windows silently strips trailing spaces and dots, so "
                        "the folder would not have the name in the sheet and "
                        "the ledger would disagree with the disk.")})
            continue

        target = old.parent / new_name
        length = len(str(target))
        budget = length + (deepest_child_len or 0)
        if budget > MAX_PATH:
            problems.append({
                "row": item["row"], "kind": "path_too_long",
                "detail": f"{length} chars, +{deepest_child_len or 0} deepest "
                          f"child = {budget}",
                "why": (f"Over the {MAX_PATH}-character limit. The rename may "
                        f"appear to work while files deep inside become "
                        f"unopenable by ordinary tools.")})
            continue

        key = str(target).lower()
        if key in seen_targets:
            problems.append({
                "row": item["row"], "kind": "duplicate_target",
                "detail": f"{target} also from row {seen_targets[key]}",
                "why": ("Two folders cannot share a name. Windows compares "
                        "case-insensitively, so these collide even if the "
                        "spreadsheet spells them differently.")})
            continue
        seen_targets[key] = item["row"]

        if not old.exists():
            problems.append({
                "row": item["row"], "kind": "source_missing",
                "detail": str(old),
                "why": ("The folder is not there. It may already have been "
                        "renamed - check the ledger before assuming the sheet "
                        "is wrong.")})
            continue
        if target.exists() and str(target).lower() != str(old).lower():
            problems.append({
                "row": item["row"], "kind": "target_exists",
                "detail": str(target),
                "why": ("Something is already there. Renaming onto it would "
                        "merge or fail depending on the filesystem, and "
                        "neither is what the sheet asked for.")})
            continue
        item["new_path"] = str(target)
        item["case_only"] = str(target).lower() == str(old).lower()
    ok = [i for i in plan if "new_path" in i]
    return ok, problems


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #
def load_ledger(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"renames": [], "created_utc": _dt.datetime.now(
            _dt.timezone.utc).isoformat()}
    except json.JSONDecodeError as exc:
        raise RenameError(
            f"{path} is not valid JSON ({exc}). This file is the ONLY record "
            f"linking old paths to new ones - without it a renamed folder "
            f"cannot be found from a path someone wrote down, and no rename "
            f"can be undone. Do not delete it, and do not proceed until it "
            f"reads.")


def save_ledger(ledger, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Written to a temporary file and moved into place, so an interruption
    # leaves the previous ledger intact rather than a half-written one. The
    # ledger is the only thing standing between a rename and data loss.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return str(p)


def apply(plan, ledger_path, *, dry_run=True, note=""):
    """Do the renames. Does NOTHING unless dry_run is explicitly False."""
    ledger = load_ledger(ledger_path)
    done, failed = [], []
    stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    who = _who()

    for item in plan:
        if "new_path" not in item:
            continue
        old, new = Path(item["old_path"]), Path(item["new_path"])
        record = {
            "old_path": str(old), "new_path": str(new),
            "old_name": old.name, "new_name": new.name,
            "utc": stamp, "by": who, "note": note or item.get("note", ""),
            "row": item.get("row"),
        }
        if dry_run:
            record["dry_run"] = True
            done.append(record)
            continue
        try:
            if item.get("case_only"):
                # A case-only rename needs two steps on Windows: the
                # filesystem considers source and target the same name and
                # will not act, so it goes via a temporary.
                mid = old.parent / (old.name + "__case_tmp__")
                os.rename(old, mid)
                os.rename(mid, new)
            else:
                os.rename(old, new)
        except OSError as exc:
            record["error"] = str(exc)
            record["likely_cause"] = (
                "A folder open in Explorer or a file open in Fiji will refuse "
                "to be renamed. That is transient - close it and re-run; the "
                "ledger does not record this as done."
                if getattr(exc, "winerror", None) in (32, 5) else
                "See the error above.")
            failed.append(record)
            continue
        if not new.exists():
            record["error"] = "rename reported success but the target is absent"
            failed.append(record)
            continue
        record["verified"] = True
        done.append(record)
        ledger["renames"].append(record)
        # Saved after EVERY rename, not at the end. An interruption partway
        # through 300 folders must leave a ledger that matches the disk.
        save_ledger(ledger, ledger_path)

    return {
        "dry_run": bool(dry_run),
        "n_planned": len([i for i in plan if "new_path" in i]),
        "n_done": len(done), "n_failed": len(failed),
        "done": done, "failed": failed,
        "ledger": ledger_path,
        "note": ("Nothing was changed. Re-run with dry_run=False to apply."
                 if dry_run else
                 f"{len(done)} folder(s) renamed and recorded."),
    }


# --------------------------------------------------------------------------- #
# Living with the result
# --------------------------------------------------------------------------- #
def resolve(old_path, ledger_path):
    """Where is this now? Follows a chain of renames, not just one.

    The reason a ledger is worth keeping: a path written in a notebook in 2024
    still resolves in 2031, through however many renames happened between.
    """
    ledger = load_ledger(ledger_path)
    current = str(Path(old_path))
    chain = []
    # ONE PASS, IN THE ORDER THE RENAMES HAPPENED. Repeatedly re-searching the
    # whole ledger from the current name looks equivalent and is not: once a
    # folder has been renamed A->B->C and then undone C->B, that search finds
    # B->C again and ping-pongs forever. Replaying history forwards cannot
    # cycle, because each entry is consulted once and an undo is simply a
    # later entry that moves the name back.
    for r in ledger["renames"]:
        if current.lower() == r["old_path"].lower():
            current = r["new_path"]
            chain.append(current)
            continue
        # A path INSIDE a renamed folder moves with it.
        prefix = r["old_path"].rstrip("\\/") + os.sep
        if current.lower().startswith(prefix.lower()):
            current = r["new_path"] + current[len(r["old_path"]):]
            chain.append(current)
    return {
        "original": str(Path(old_path)), "current": current,
        "moved": bool(chain), "chain": chain,
        "exists_now": Path(current).exists(),
        "why": (None if chain else
                "No rename recorded for this path - either it was never "
                "renamed, or it was renamed outside this ledger."),
    }


def undo(ledger_path, *, rows=None, dry_run=True):
    """Put names back. Newest first, since renames can nest."""
    ledger = load_ledger(ledger_path)
    todo = [r for r in reversed(ledger["renames"])
            if rows is None or r.get("row") in set(rows)]
    reverted, failed = [], []
    for r in todo:
        new, old = Path(r["new_path"]), Path(r["old_path"])
        if dry_run:
            reverted.append({**r, "dry_run": True})
            continue
        if not new.exists():
            failed.append({**r, "error": "current path no longer exists"})
            continue
        if old.exists():
            failed.append({**r, "error": (
                "the original name is occupied again - undoing would collide")})
            continue
        try:
            os.rename(new, old)
        except OSError as exc:
            failed.append({**r, "error": str(exc)})
            continue
        reverted.append(r)
        # The undo is itself recorded. A ledger that forgets its own reversals
        # would resolve old paths to folders that no longer carry those names.
        ledger["renames"].append({
            "old_path": r["new_path"], "new_path": r["old_path"],
            "old_name": r["new_name"], "new_name": r["old_name"],
            "utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "by": _who(), "note": f"undo of row {r.get('row')}",
            "is_undo": True, "verified": True})
        save_ledger(ledger, ledger_path)
    return {"dry_run": bool(dry_run), "n_reverted": len(reverted),
            "n_failed": len(failed), "reverted": reverted, "failed": failed}


def write_crosswalk(ledger_path, csv_path):
    """A flat old-to-new table, for anyone who will never open a JSON file."""
    ledger = load_ledger(ledger_path)
    p = Path(csv_path)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["old_path", "new_path", "old_name", "new_name",
                    "when_utc", "by", "is_undo", "note"])
        for r in ledger["renames"]:
            w.writerow([r["old_path"], r["new_path"], r["old_name"],
                        r["new_name"], r["utc"], r.get("by") or "",
                        r.get("is_undo", False), r.get("note", "")])
    return str(p)
