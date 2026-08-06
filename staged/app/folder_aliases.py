"""Meaningful names for folders, without renaming anything.

Andres asked whether a folder could be given a nickname while keeping its real
name. It can, and it is strictly better than renaming.

WHAT WAS MEASURED ON THIS SYSTEM, rather than assumed:

  DIRECTORY SYMLINKS WORK AND ARE FULLY TRANSPARENT. Explorer, Python and Fiji
  all see a real directory - `exists`, `is_dir`, `listdir` and opening a file
  through one all behave normally. Developer mode is enabled on this machine so
  they need no administrator rights.

  JUNCTIONS DO NOT WORK on the lab drive: "Local volumes are required to
  complete the operation." They are the usual advice and they are wrong here.

  SHORTCUTS (.lnk) ARE NOT TRANSPARENT. Python sees a FILE, not a directory, so
  no analysis can open a path through one. They are fine for a human clicking
  in Explorer and useless to every tool. Offered as a fallback, clearly marked.

  SYMLINKS CANNOT BE CREATED ON THE LAB DRIVE ITSELF - access denied by the
  server. So the view tree lives on a local disk.

THAT LAST CONSTRAINT SHAPES THE DESIGN, and improves it. The CATALOGUE - the
mapping from real folder to meaningful name - lives on the lab drive and is
shared. The view tree is generated locally on each machine from that catalogue,
and regenerating is cheap and idempotent. Nobody can break anyone else's view
by deleting a link, and each person can build only the views they care about.

WHY THIS BEATS RENAMING. Nothing breaks: every path stored in an analysis CSV,
a geometry sidecar, a Fiji script or a manuscript still resolves, because the
real folder never moved. There is nothing to undo - a wrong nickname is fixed
by deleting a link. Both names work at once. And the catalogue can hold several
nicknames for one folder, which a rename cannot.

TWO REAL HAZARDS, worth stating plainly rather than discovering:

  A recursive delete THROUGH a symlink can delete the target. `rm -rf` on a
  view directory is capable of destroying the real data. This module never
  deletes recursively and `remove_views` unlinks the links themselves only.

  Backup software may FOLLOW symlinks and copy the target, which would back up
  1.6 TB of lab drive into a local backup. Keep the view tree out of anything
  that syncs - not inside OneDrive.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
from pathlib import Path

ILLEGAL = set('<>:"/\\|?*')


class AliasError(Exception):
    """Refusals that name the consequence."""


def _who():
    try:
        import operator_identity
        return operator_identity.initials() or None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# The catalogue: the shared, portable source of truth
# --------------------------------------------------------------------------- #
def load_catalogue(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"entries": [], "created_utc": _dt.datetime.now(
            _dt.timezone.utc).isoformat()}
    except json.JSONDecodeError as exc:
        raise AliasError(
            f"{path} is not valid JSON ({exc}). This is the shared record of "
            f"what every folder actually contains - the view trees on every "
            f"machine are generated from it, and it is the only thing that is "
            f"not reproducible from the drive itself.")


def save_catalogue(cat, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cat, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return str(p)


def read_names_csv(csv_path, *, path_col="path", name_col="new_name",
                   group_col="group", note_col="note"):
    """Read the spreadsheet of assigned names. Blanks mean 'not named yet'."""
    entries = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if path_col not in (reader.fieldnames or []):
            raise AliasError(
                f"No {path_col!r} column in {csv_path}. The real path is what "
                f"an alias points AT; a folder name alone is ambiguous on this "
                f"drive, where 'w2' and 'Raw Data' appear under many people.")
        for i, row in enumerate(reader, start=2):
            name = (row.get(name_col) or "").strip()
            if not name:
                continue
            entries.append({
                "row": i,
                "real_path": (row.get(path_col) or "").strip(),
                "alias": name,
                "group": (row.get(group_col) or "").strip(),
                "note": (row.get(note_col) or "").strip(),
            })
    return entries


def check_names(entries, *, require_exists=True):
    """Validate before anything is created. Aliases may repeat across groups."""
    ok, problems, seen = [], [], {}
    for e in entries:
        alias, real = e["alias"], Path(e["real_path"])
        bad = sorted(set(alias) & ILLEGAL)
        if bad:
            problems.append({"row": e["row"], "kind": "illegal_characters",
                             "detail": f"{alias!r} contains {''.join(bad)}",
                             "why": "Windows cannot create it."})
            continue
        if alias != alias.strip(" ."):
            problems.append({"row": e["row"], "kind": "trailing_space_or_dot",
                             "detail": repr(alias),
                             "why": ("Windows strips these silently, so the "
                                     "link would not carry the name in the "
                                     "sheet.")})
            continue
        key = (e["group"].lower(), alias.lower())
        if key in seen:
            problems.append({
                "row": e["row"], "kind": "duplicate_alias",
                "detail": f"{alias!r} in group {e['group']!r} also at row "
                          f"{seen[key]}",
                "why": ("Two links cannot share a name in one folder. The same "
                        "alias in a DIFFERENT group is fine and is not "
                        "flagged.")})
            continue
        seen[key] = e["row"]
        if require_exists and not real.exists():
            problems.append({
                "row": e["row"], "kind": "target_missing", "detail": str(real),
                "why": ("The folder is not there. A link to nothing looks "
                        "identical to a link to something until it is opened.")})
            continue
        ok.append(e)
    return ok, problems


def catalogue_from_names(entries, existing=None):
    """Fold assigned names into the catalogue. One folder may hold several."""
    cat = existing or {"entries": [],
                       "created_utc": _dt.datetime.now(
                           _dt.timezone.utc).isoformat()}
    index = {(e["real_path"].lower(), e["alias"].lower(), e.get("group", ""))
             for e in cat["entries"]}
    when = _dt.datetime.now(_dt.timezone.utc).isoformat()
    who = _who()
    for e in entries:
        key = (e["real_path"].lower(), e["alias"].lower(), e.get("group", ""))
        if key in index:
            continue
        cat["entries"].append({**e, "added_utc": when, "by": who})
        index.add(key)
    return cat


# --------------------------------------------------------------------------- #
# The view tree: generated locally, disposable, regenerable
# --------------------------------------------------------------------------- #
def build_views(catalogue, view_root, *, dry_run=True, method="symlink",
                overwrite=False):
    """Create the nickname tree. Nothing is created unless dry_run is False.

    `method` is "symlink" (transparent to every tool) or "shortcut" (visible in
    Explorer only, and useless to any analysis - measured, not assumed).
    """
    if method not in {"symlink", "shortcut"}:
        raise AliasError("method must be 'symlink' or 'shortcut'.")
    root = Path(view_root)
    entries = catalogue.get("entries", [])

    # A view tree inside the data would be walked by the surveys and analysed
    # as if it were data, and a recursive delete there could reach the real
    # folders through the links.
    for e in entries:
        real = Path(e["real_path"])
        try:
            if root.resolve() == real.resolve() or root.resolve() in \
                    real.resolve().parents:
                raise AliasError(
                    f"The view root {root} sits inside the data at {real}. "
                    f"Links there would be surveyed as if they were "
                    f"experiments, and a recursive delete could reach the real "
                    f"folders through them. Put the view tree somewhere "
                    f"separate and local.")
        except OSError:
            pass

    made, skipped, failed = [], [], []
    for e in entries:
        real = Path(e["real_path"])
        link = root / e["group"] / e["alias"] if e.get("group") else \
            root / e["alias"]
        rec = {"alias": e["alias"], "group": e.get("group", ""),
               "link": str(link), "real_path": str(real)}
        if link.exists() or link.is_symlink():
            if not overwrite:
                skipped.append({**rec, "reason": "already exists"})
                continue
            if not dry_run:
                try:
                    # UNLINK ONLY. Never a recursive delete - through a symlink
                    # that would reach the real data.
                    link.unlink()
                except OSError as exc:
                    failed.append({**rec, "error": f"could not replace: {exc}"})
                    continue
        if dry_run:
            made.append({**rec, "dry_run": True})
            continue
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            if method == "symlink":
                os.symlink(real, link, target_is_directory=True)
            else:
                _make_shortcut(real, link.with_suffix(".lnk"))
                rec["link"] = str(link.with_suffix(".lnk"))
        except OSError as exc:
            failed.append({**rec, "error": str(exc), "likely_cause": (
                "Symlink creation needs developer mode or admin rights, and "
                "cannot be done ON a network share - only pointing at one.")})
            continue
        made.append(rec)

    out = {"dry_run": bool(dry_run), "method": method,
           "view_root": str(root), "n_made": len(made),
           "n_skipped": len(skipped), "n_failed": len(failed),
           "made": made, "skipped": skipped, "failed": failed}
    if method == "shortcut":
        out["warning"] = (
            "Shortcuts are visible in Explorer and INVISIBLE to code - Python "
            "sees a file, not a directory, so no analysis can open a path "
            "through one. Use symlinks for anything a tool will read.")
    if dry_run:
        out["note"] = "Nothing was created. Re-run with dry_run=False."
    return out


def _make_shortcut(target, link_path):
    import subprocess
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
          f"'{link_path}'); $s.TargetPath='{target}'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True)


def verify_views(view_root):
    """Do the links still point at something? Cheap, and worth running."""
    root = Path(view_root)
    if not root.exists():
        return {"exists": False, "why": f"No view tree at {root}."}
    live, dead, notlinks = [], [], []
    for p in root.rglob("*"):
        if p.is_symlink():
            (live if p.exists() else dead).append(
                {"link": str(p), "target": str(os.readlink(p))})
        elif p.suffix.lower() == ".lnk":
            notlinks.append(str(p))
    out = {"exists": True, "n_live": len(live), "n_dead": len(dead),
           "n_shortcuts": len(notlinks), "dead": dead}
    if dead:
        out["warning"] = (
            f"{len(dead)} link(s) point at folders that are no longer there. "
            f"The drive may be disconnected - check that before concluding "
            f"anything was moved, because a dead link and an unmounted share "
            f"look identical.")
    return out


def remove_views(view_root, *, dry_run=True):
    """Delete the links themselves. NEVER recursive, never through a link."""
    root = Path(view_root)
    removed = []
    if not root.exists():
        return {"dry_run": dry_run, "n_removed": 0,
                "why": f"No view tree at {root}."}
    for p in sorted(root.rglob("*"), key=lambda q: -len(str(q))):
        if p.is_symlink() or p.suffix.lower() == ".lnk":
            removed.append(str(p))
            if not dry_run:
                p.unlink()
    return {"dry_run": bool(dry_run), "n_removed": len(removed),
            "removed": removed,
            "safety": ("Only links were unlinked. Nothing recursive was run, "
                       "because a recursive delete through a symlink can "
                       "destroy the real data it points at.")}


def find(catalogue, text):
    """Search aliases and notes - the point of having given things names."""
    t = str(text).lower()
    return [e for e in catalogue.get("entries", [])
            if t in e.get("alias", "").lower()
            or t in e.get("note", "").lower()
            or t in e.get("group", "").lower()
            or t in e.get("real_path", "").lower()]
