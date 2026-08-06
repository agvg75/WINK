"""Let a person fix the tracker: join, split, add, delete.

Andres: as in the population tracker, the user should be able to fix tracks -
connect, add, split and so on.

EVERY EDIT IS RECORDED, and that is the part that matters. A corrected track
and an uncorrected one look identical afterwards, so without a log there is no
way to tell a dataset somebody curated from one nobody looked at, and no way
to answer "who decided these two fragments were the same animal" a year later.
The edit log travels with the tracks.

NOTHING IS DESTROYED. A deleted track is marked deleted and kept, because
"this blob was a dust speck" is a judgement that can be wrong, and the person
who has to revisit it is usually not the person who made it. Undo is possible
only because nothing is thrown away.

THE JOIN IS THE DANGEROUS EDIT. Splitting one track into two is conservative -
it can only reduce what is claimed. Joining asserts that two fragments are the
SAME ANIMAL, and a wrong join fabricates a trajectory that no worm took: a
displacement that never happened, at a speed nothing achieved, pointing in a
direction nobody swam. So joins are checked for overlap in time and for the
implied speed, and the check refuses rather than warns when the fragments
coexist - two tracks present in the same frame cannot be one animal.
"""
from __future__ import annotations

import datetime as _dt

import numpy as np


class TrackEditError(Exception):
    """Refusals that name the consequence."""


def _who():
    try:
        import operator_identity
        return operator_identity.initials() or None
    except Exception:
        return None


def _rows(tracks, worm_id):
    rows = [r for r in tracks if str(r.get("worm_id")) == str(worm_id)]
    if not rows:
        raise TrackEditError(
            f"No track called {worm_id!r}. Editing a track that does not "
            f"exist would silently do nothing and look like it worked.")
    return sorted(rows, key=lambda r: float(r["time_s"]))


class TrackSet:
    """Tracks plus the record of what a person changed about them."""

    def __init__(self, rows, um_per_px=None, fps=None):
        self.rows = [dict(r) for r in rows]
        self.um_per_px = um_per_px
        self.fps = fps
        self.log = []
        self.deleted = {}

    # ------------------------------------------------------------------ #
    def _record(self, action, **detail):
        entry = {"action": action,
                 "utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                 "by": _who()}
        entry.update(detail)
        if entry["by"] is None:
            entry["unattributed"] = (
                "Nobody was set at this station, so this correction has no "
                "author. A curated dataset and an untouched one look "
                "identical afterwards; the log is the only difference.")
        self.log.append(entry)
        return entry

    def worm_ids(self):
        return sorted({str(r.get("worm_id")) for r in self.rows})

    def active(self):
        """Rows excluding deleted tracks - what analysis should consume."""
        return [r for r in self.rows
                if str(r.get("worm_id")) not in self.deleted]

    # ------------------------------------------------------------------ #
    def join(self, a, b, *, new_id=None, max_speed_mm_s=None, force=False,
             reason=""):
        """Assert two fragments are one animal. The dangerous edit."""
        ra, rb = _rows(self.rows, a), _rows(self.rows, b)
        first, second = (ra, rb) if float(ra[-1]["time_s"]) <= float(
            rb[0]["time_s"]) else (rb, ra)
        if float(second[0]["time_s"]) <= float(first[-1]["time_s"]):
            raise TrackEditError(
                f"Tracks {a!r} and {b!r} overlap in time "
                f"({float(second[0]['time_s'])} <= "
                f"{float(first[-1]['time_s'])}). Two tracks present in the "
                f"same frame cannot be one animal - joining them would "
                f"fabricate a trajectory that no worm took. Split one first "
                f"if the overlap is itself a tracking error.")
        gap_s = float(second[0]["time_s"]) - float(first[-1]["time_s"])
        jump = float(np.hypot(
            float(second[0]["x_mm"]) - float(first[-1]["x_mm"]),
            float(second[0]["y_mm"]) - float(first[-1]["y_mm"])))
        speed = jump / gap_s if gap_s > 0 else float("inf")
        if max_speed_mm_s and speed > float(max_speed_mm_s) and not force:
            raise TrackEditError(
                f"Joining {a!r} to {b!r} implies {jump:.2f} mm in {gap_s:.2f} "
                f"s, which is {speed:.2f} mm/s - above the {max_speed_mm_s} "
                f"mm/s this animal can manage. The join would invent a "
                f"displacement that never happened. Pass force=True with a "
                f"reason if the gap is a dropped-frame artefact rather than a "
                f"real separation.")
        target = str(new_id or first[0].get("worm_id"))
        for r in self.rows:
            if str(r.get("worm_id")) in {str(a), str(b)}:
                r["worm_id"] = target
                r.setdefault("edited", []).append("joined")
        self._record("join", a=str(a), b=str(b), into=target,
                     gap_s=gap_s, jump_mm=jump, implied_speed_mm_s=speed,
                     forced=bool(force), reason=reason)
        return target

    def split(self, worm_id, at_time_s, *, new_id=None, reason=""):
        """Two animals were being tracked as one. Conservative by nature."""
        rows = _rows(self.rows, worm_id)
        t = float(at_time_s)
        if not (float(rows[0]["time_s"]) < t <= float(rows[-1]["time_s"])):
            raise TrackEditError(
                f"Time {t} is outside track {worm_id!r} "
                f"({rows[0]['time_s']} to {rows[-1]['time_s']}). A split "
                f"outside the track would leave it unchanged while reporting "
                f"success.")
        target = str(new_id or f"{worm_id}_b")
        if target in self.worm_ids():
            raise TrackEditError(
                f"{target!r} already exists, and reusing an id would merge "
                f"this fragment into an unrelated animal.")
        n = 0
        for r in self.rows:
            if str(r.get("worm_id")) == str(worm_id) and float(r["time_s"]) >= t:
                r["worm_id"] = target
                r.setdefault("edited", []).append("split")
                n += 1
        self._record("split", worm_id=str(worm_id), at_time_s=t,
                     new_id=target, rows_moved=n, reason=reason)
        return target

    def delete(self, worm_id, *, reason=""):
        """Mark a track as not an animal. Kept, never removed."""
        _rows(self.rows, worm_id)
        if not reason:
            raise TrackEditError(
                "A deletion needs a reason. 'This was a dust speck' is a "
                "judgement that can be wrong, and the person who revisits it "
                "is usually not the person who made it.")
        self.deleted[str(worm_id)] = reason
        self._record("delete", worm_id=str(worm_id), reason=reason)
        return str(worm_id)

    def restore(self, worm_id):
        if str(worm_id) not in self.deleted:
            raise TrackEditError(f"{worm_id!r} is not deleted.")
        reason = self.deleted.pop(str(worm_id))
        self._record("restore", worm_id=str(worm_id), was=reason)
        return str(worm_id)

    def add(self, worm_id, points, *, reason=""):
        """A worm the tracker missed entirely, traced by hand."""
        if str(worm_id) in self.worm_ids():
            raise TrackEditError(
                f"{worm_id!r} already exists. Adding to it by hand would mix "
                f"traced points with detected ones under the same name and "
                f"nothing downstream could tell them apart.")
        pts = list(points)
        if len(pts) < 2:
            raise TrackEditError(
                "A hand-added track needs at least two points; one point is a "
                "position, not a trajectory.")
        for p in pts:
            row = dict(p)
            row["worm_id"] = str(worm_id)
            # Hand-added points are marked forever. A traced position and a
            # detected one have different uncertainties and should never be
            # pooled without knowing which is which.
            row["hand_added"] = True
            row.setdefault("edited", []).append("added")
            self.rows.append(row)
        self._record("add", worm_id=str(worm_id), n_points=len(pts),
                     reason=reason)
        return str(worm_id)

    # ------------------------------------------------------------------ #
    def summary(self):
        """What was changed, for the provenance record and for the reader."""
        counts = {}
        for e in self.log:
            counts[e["action"]] = counts.get(e["action"], 0) + 1
        hand = sum(1 for r in self.rows if r.get("hand_added"))
        out = {
            "n_tracks": len(self.worm_ids()),
            "n_deleted": len(self.deleted),
            "n_edits": len(self.log),
            "edits_by_kind": counts,
            "hand_added_points": hand,
            "log": list(self.log),
            "edited": bool(self.log),
        }
        if not self.log:
            out["note"] = (
                "No corrections were made. That is a fact about this session, "
                "not a guarantee the tracking was right - nobody may have "
                "looked.")
        forced = [e for e in self.log if e.get("forced")]
        if forced:
            out["forced_joins"] = len(forced)
            out["warning"] = (
                f"{len(forced)} join(s) were forced past the speed check. Each "
                f"asserts a displacement the animal could not have made "
                f"unless frames were dropped; check the reasons before "
                f"trusting the affected trajectories.")
        if self.deleted:
            out["deleted_tracks"] = dict(self.deleted)
        return out
