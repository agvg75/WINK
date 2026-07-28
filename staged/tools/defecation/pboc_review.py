"""Versioned, non-destructive review state and finalization for pBoc events."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

import numpy as np

SCHEMA_VERSION = "1.0"
DECISIONS = {"pending", "accepted", "rejected"}


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def source_identity(folder, paths):
    files = list(paths)
    return {
        "folder": str(Path(folder).resolve()),
        "frame_count": len(files),
        "first_frame": files[0].name if files else None,
        "last_frame": files[-1].name if files else None,
        "total_bytes": sum(path.stat().st_size for path in files),
    }


def automatic_events(summary):
    events = []
    for number, candidate in enumerate(summary.get("events", []), 1):
        peak = int(candidate["peak_frame"])
        recovery = candidate.get("recovery_frame")
        recovery = None if recovery is None else int(recovery)
        events.append({
            "event_id": f"auto-{number:04d}",
            "provenance": "automatic",
            "auto_peak_frame": peak,
            "auto_peak_time_s": float(candidate.get(
                "peak_time_s", peak / float(summary["fps"]))),
            "reviewed_peak_frame": peak,
            "reviewed_peak_time_s": peak / float(summary["fps"]),
            "auto_recovery_frame": recovery,
            "auto_recovery_time_s": (
                None if recovery is None else recovery / float(summary["fps"])),
            "reviewed_recovery_frame": recovery,
            "reviewed_recovery_time_s": (
                None if recovery is None else recovery / float(summary["fps"])),
            "peak_z": _clean(candidate.get("peak_z")),
            "decision": "pending",
            "review_note": "",
            "automatic_review_priority": candidate.get("review_note", ""),
            "reviewed_at": None,
        })
    return events


class ReviewState:
    def __init__(self, summary, full_scan, source_folder, frame_paths,
                 review_path):
        self.summary = summary
        self.scan = full_scan
        self.source_folder = Path(source_folder)
        self.paths = list(frame_paths)
        self.review_path = Path(review_path)
        self.fps = float(summary["fps"])
        self.events = automatic_events(summary)
        self.finalized = None
        if self.review_path.is_file():
            self.load()

    def candidate_signature(self):
        return [event.get("auto_peak_frame") for event in self.events
                if event.get("provenance") == "automatic"]

    def document(self):
        return _clean({
            "review_schema_version": SCHEMA_VERSION,
            "recording": self.summary["recording"],
            "source": str(self.source_folder),
            "source_recording_identity": source_identity(
                self.source_folder, self.paths),
            "analysis_settings": self.summary.get("settings", {}),
            "analysis_source": self.summary.get("analysis_source", {}),
            "events": self.events,
            "candidate_signature": self.candidate_signature(),
            "finalization": self.finalized,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        })

    def save(self):
        self.review_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            self.document(), indent=2, allow_nan=False).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(
            prefix=self.review_path.name + ".", suffix=".tmp",
            dir=str(self.review_path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(5):
                try:
                    os.replace(temp_name, self.review_path)
                    break
                except PermissionError:
                    if attempt == 4: raise
                    time.sleep(.05 * (attempt + 1))
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load(self):
        data = json.loads(self.review_path.read_text(encoding="utf-8-sig"))
        version = str(data.get("review_schema_version", ""))
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported pBoc review schema: {version}")
        current_signature = self.candidate_signature()
        saved_signature = data.get("candidate_signature")
        if saved_signature is not None and saved_signature != current_signature:
            archive = self.review_path.with_name(
                self.review_path.stem + ".pre_reanalysis.json")
            archive.write_bytes(self.review_path.read_bytes())
            return
        saved = {event["event_id"]: event for event in data.get("events", [])}
        merged = []
        for event in self.events:
            merged.append(saved.pop(event["event_id"], event))
        merged.extend(saved.values())
        self.events = merged
        self.finalized = data.get("finalization")
        self.sort_events()

    def sort_events(self):
        self.events.sort(key=lambda e: (
            int(e["reviewed_peak_frame"]), e["event_id"]))

    def add(self, frame):
        event = {
            "event_id": "manual-" + uuid.uuid4().hex[:12],
            "provenance": "manual",
            "auto_peak_frame": None, "auto_peak_time_s": None,
            "reviewed_peak_frame": int(frame),
            "reviewed_peak_time_s": int(frame) / self.fps,
            "auto_recovery_frame": None, "auto_recovery_time_s": None,
            "reviewed_recovery_frame": None,
            "reviewed_recovery_time_s": None,
            "peak_z": self.value_at(frame, "score_z"),
            "decision": "pending", "review_note": "",
            "automatic_review_priority": "manual_addition",
            "reviewed_at": None,
        }
        self.events.append(event); self.sort_events(); self.save()
        return event

    def update(self, event, *, decision=None, peak=None, recovery="unchanged",
               note=None):
        if decision is not None:
            if decision not in DECISIONS:
                raise ValueError("Unknown review decision.")
            event["decision"] = decision
        if peak is not None:
            event["reviewed_peak_frame"] = int(peak)
            event["reviewed_peak_time_s"] = int(peak) / self.fps
            event["peak_z"] = self.value_at(peak, "score_z")
        if recovery != "unchanged":
            event["reviewed_recovery_frame"] = (
                None if recovery is None else int(recovery))
            event["reviewed_recovery_time_s"] = (
                None if recovery is None else int(recovery) / self.fps)
        if note is not None:
            event["review_note"] = str(note)
        event["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        self.sort_events(); self.save()

    def delete_manual(self, event):
        if event.get("provenance") != "manual":
            raise ValueError("Automatic candidates cannot be deleted; reject them.")
        self.events.remove(event); self.save()

    def value_at(self, frame, column):
        try:
            value = float(self.scan.iloc[int(frame)][column])
            return value if np.isfinite(value) else None
        except Exception:
            return None

    def usable_summary(self):
        usable = self.scan["usable"].astype(bool).to_numpy()
        runs = []
        start = None
        for i, value in enumerate(np.r_[usable, False]):
            if value and start is None: start = i
            if not value and start is not None:
                runs.append((start, i - 1)); start = None
        return {
            "usable_frames": int(usable.sum()),
            "total_frames": int(len(usable)),
            "usable_percentage": float(100 * usable.mean()) if len(usable) else 0,
            "continuous_usable_runs": len(runs),
            "longest_usable_run_frames": max(
                (end - start + 1 for start, end in runs), default=0),
        }

    def tracking_warning(self, event):
        usable = self.scan["usable"].astype(bool).to_numpy()
        peak = int(event["reviewed_peak_frame"])
        recovery = event.get("reviewed_recovery_frame")
        end = peak if recovery is None else int(recovery)
        lo, hi = max(0, peak - 1), min(len(usable), end + 2)
        if lo >= hi or not usable[lo:hi].all():
            return "Event is adjacent to or interrupted by unusable tracking."
        return ""

    def finalize(self, minimum_accepted=10):
        counts = {name: sum(e["decision"] == name for e in self.events)
                  for name in DECISIONS}
        counts["manually_added"] = sum(
            e.get("provenance") == "manual" for e in self.events)
        reasons = []
        if counts["pending"]:
            reasons.append(f"{counts['pending']} candidate(s) remain pending")
        accepted = sorted(
            (e for e in self.events if e["decision"] == "accepted"),
            key=lambda e: int(e["reviewed_peak_frame"]))
        frames = [int(e["reviewed_peak_frame"]) for e in accepted]
        if len(set(frames)) != len(frames):
            reasons.append("accepted peak frames are not unique")
        for event in accepted:
            recovery = event.get("reviewed_recovery_frame")
            if recovery is not None and int(recovery) <= int(
                    event["reviewed_peak_frame"]):
                reasons.append(
                    f"{event['event_id']} recovery is not after its peak")
            warning = self.tracking_warning(event)
            if warning:
                reasons.append(f"{event['event_id']}: {warning}")
        if len(accepted) < minimum_accepted:
            reasons.append(
                f"only {len(accepted)} accepted events; at least "
                f"{minimum_accepted} are required")
        if len(frames) >= 2:
            usable = self.scan["usable"].astype(bool).to_numpy()
            if not usable[min(frames):max(frames) + 1].all():
                reasons.append(
                    "tracking is not continuously usable from the first to "
                    "the last accepted event")
        intervals = np.diff(np.asarray(frames, float) / self.fps)
        stats = None
        if not reasons and len(intervals):
            stats = {
                "accepted_event_count": len(accepted),
                "period_mean_s": float(np.mean(intervals)),
                "idi_s": intervals.tolist(),
                "idi_cv": (None if np.mean(intervals) == 0 else
                           float(np.std(intervals, ddof=1) / np.mean(intervals))),
            }
        self.finalized = {
            "finalized_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts, "eligible": not reasons,
            "ineligibility_reasons": reasons,
            "statistics": stats,
            "events_used": [e["event_id"] for e in accepted] if stats else [],
        }
        self.save()
        return self.finalized
