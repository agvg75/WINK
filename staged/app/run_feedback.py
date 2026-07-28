"""First-run briefings and post-run feedback backed by the Failure Library.

Briefing acknowledgments are version-specific. A new tool version can therefore
show revised warnings once without nagging on every launch. Run outcomes include
clean runs, providing the denominator needed to interpret failure frequency.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable
from urllib.parse import quote

from acquisition import AcquisitionMetadata
from failure_library import FAILURE_CATEGORIES, FailureContext, FailureLibrary

SUPPORT_EMAIL = "VidalGadeaLab@gmail.com"
SUPPORT_SUBJECT_PREFIX = "[AGVG-LAB-TOOLS][ISSUE]"
SUPPORT_BUNDLE_MAX_BYTES = 18 * 1024 * 1024


def user_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AGVGLab" / "quality"
    return Path.home() / ".agvg_lab_tools" / "quality"


@dataclass(frozen=True)
class ToolBriefing:
    tool_name: str
    tool_version: str
    biological_unit: str
    watch_parameters: tuple[str, ...]
    null_safeguard: str
    review_reminder: str = (
        "Automated detections are proposals. Inspect and correct overlays "
        "before export.")

    def text(self) -> str:
        watch = "\n".join(f"• {item}" for item in self.watch_parameters)
        return (
            f"Biological unit: {self.biological_unit}\n\n"
            f"Parameters and failure points to watch:\n{watch}\n\n"
            f"Null safeguard: {self.null_safeguard}\n\n"
            f"{self.review_reminder}\n\n"
            "After the run, please record whether it was clean or report an "
            "issue. This improves the shared failure-mode tally.")


BRIEFINGS = {
    "Population orientation (Plate state)": ToolBriefing(
        "Population orientation (Plate state)", "0.1.0", "plate",
        ("Confirm FPS and two-point scale calibration.",
         "Confirm stimulus, control, and release positions.",
         "Inspect segmentation and exclude occlusions or merged animals.",
         "Do not interpret a single stimulus orientation as proof of response."),
        "A sham/no-stimulus plate and lab-frame direction are required."),
    "Population swimming + modality review (Experimental)": ToolBriefing(
        "Population swimming + modality review (Experimental)", "0.1.0",
        "worm aggregated to plate",
        ("FPS and exposure are different constants; declare both.",
         "Check blur, truncation, coils, and unusable frames.",
         "Do not assign dorsal/ventral identity without an anatomical anchor.",
         "Review proposed swimming/crawling/burrowing bouts."),
        "A flat non-decaying bout is a valid no-fatigue outcome."),
    "Neuron tracker": ToolBriefing(
        "Neuron tracker", "0.1.0", "one neuron in one worm",
        ("Check for transmitted-light or brightfield anchor frames.",
         "Watch gut-granule competitors near the target.",
         "Inspect every low-signal interval and manual-relink flag.",
         "Keep absolute F0 distinct from relative dF/F."),
        "The feasibility pass may return 'do not attempt this movie'."),
}


class RunFeedbackStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else user_data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ack_path = self.root / "briefing_acknowledgments.json"
        self.run_log = self.root / "run_outcomes.jsonl"
        self.review_log = self.root / "review_confirmations.jsonl"
        self.failure_library = FailureLibrary(self.root / "failures")

    def _acknowledgments(self) -> dict:
        if not self.ack_path.is_file():
            return {}
        try:
            return json.loads(self.ack_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def briefing_key(briefing: ToolBriefing) -> str:
        return f"{briefing.tool_name}@{briefing.tool_version}"

    def needs_briefing(self, briefing: ToolBriefing) -> bool:
        return self.briefing_key(briefing) not in self._acknowledgments()

    def acknowledge(self, briefing: ToolBriefing) -> None:
        values = self._acknowledgments()
        values[self.briefing_key(briefing)] = {
            "acknowledged_utc": datetime.now(timezone.utc).isoformat(),
            "watch_parameters": list(briefing.watch_parameters),
        }
        self.ack_path.write_text(
            json.dumps(values, indent=2), encoding="utf-8")

    def record_clean_run(
        self, *, tool_name: str, tool_version: str, run_id: str,
        acquisition: AcquisitionMetadata | None = None,
        parameters: dict | None = None,
        note: str = "",
    ) -> None:
        self._append_outcome({
            "outcome": "clean", "tool_name": tool_name,
            "tool_version": tool_version, "run_id": run_id,
            "acquisition_constants": (
                None if acquisition is None else acquisition.as_columns()),
            "parameters": parameters or {}, "note": note})

    def record_issue(
        self, *, tool_name: str, tool_version: str, run_id: str,
        acquisition: AcquisitionMetadata, category: str,
        parameters: dict, user_note: str, severity: int = 1,
        roi_coordinates=None, frame_index: int | None = None,
        evidence_paths=None,
    ) -> Path:
        if category not in FAILURE_CATEGORIES:
            raise ValueError("A fixed Failure Library category is required.")
        report = self.failure_library.capture(
            FailureContext(
                tool_name, tool_version, acquisition, category,
                roi_coordinates, frame_index, parameters, user_note,
                severity, "untriaged"),
            evidence_paths)
        self._append_outcome({
            "outcome": "issue", "tool_name": tool_name,
            "tool_version": tool_version, "run_id": run_id,
            "category": category,
            "failure_report": str(report)})
        return report

    def record_review(
        self, *, tool_name: str, tool_version: str, run_id: str,
        agreed: bool, condition: dict | None = None,
        frame_index: int | None = None, event_id: str | None = None,
        note: str = "",
    ) -> None:
        """Log inspected agreements as well as disagreements."""
        payload = {
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name, "tool_version": tool_version,
            "run_id": run_id, "review_outcome": (
                "agreement" if agreed else "disagreement"),
            "condition": condition or {}, "frame_index": frame_index,
            "event_id": event_id, "note": note,
        }
        with self.review_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")

    def review_accuracy(self) -> list[dict]:
        groups = {}
        if self.review_log.is_file():
            for line in self.review_log.read_text(
                    encoding="utf-8").splitlines():
                row = json.loads(line)
                condition = json.dumps(
                    row.get("condition", {}), sort_keys=True)
                key = (row["tool_name"], row["tool_version"], condition)
                bucket = groups.setdefault(key, {
                    "tool_name": key[0], "tool_version": key[1],
                    "condition": row.get("condition", {}),
                    "agreements": 0, "disagreements": 0})
                bucket[row["review_outcome"] + "s"] += 1
        output = []
        for row in groups.values():
            denominator = row["agreements"] + row["disagreements"]
            output.append({
                **row, "reviewed_denominator": denominator,
                "accuracy_rate": (
                    None if denominator == 0
                    else row["agreements"] / denominator),
                "validation_level": "computational_regression"})
        return sorted(
            output, key=lambda row: (
                row["tool_name"], row["tool_version"],
                json.dumps(row["condition"], sort_keys=True)))

    def _append_outcome(self, payload: dict) -> None:
        payload = {
            "recorded_utc": datetime.now(timezone.utc).isoformat(), **payload}
        with self.run_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")

    def tally(self) -> dict:
        clean = issues = 0
        categories = {}
        if self.run_log.is_file():
            for line in self.run_log.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["outcome"] == "clean":
                    clean += 1
                else:
                    issues += 1
                    category = row.get("category", "unknown")
                    categories[category] = categories.get(category, 0) + 1
        total = clean + issues
        return {
            "total_runs_reported": total, "clean_runs": clean,
            "issue_runs": issues,
            "issue_rate": None if total == 0 else issues / total,
            "categories": categories}

    def prepare_support_bundle(
        self, report_dir: str | Path, *,
        maximum_bytes: int = SUPPORT_BUNDLE_MAX_BYTES,
    ) -> dict:
        """Create a bounded ZIP. Fall back to metadata when evidence is too large."""
        report_dir = Path(report_dir)
        report_path = report_dir / "report.json"
        if not report_path.is_file():
            raise ValueError("The failure report is missing report.json.")
        export_dir = self.root / "support_bundles"
        export_dir.mkdir(parents=True, exist_ok=True)
        full_base = export_dir / report_dir.name
        full_zip = Path(shutil.make_archive(
            str(full_base), "zip", root_dir=report_dir))
        evidence_included = True
        omitted = []
        if full_zip.stat().st_size > maximum_bytes:
            full_zip.unlink()
            metadata_dir = export_dir / f"{report_dir.name}_metadata"
            metadata_dir.mkdir(exist_ok=True)
            shutil.copy2(report_path, metadata_dir / "report.json")
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            omitted = [item["file"] for item in payload.get("evidence", [])]
            (metadata_dir / "EVIDENCE_NOT_INCLUDED.txt").write_text(
                "Visual evidence remained local because the support bundle "
                "would exceed the configured size limit.\n\n" +
                "\n".join(omitted), encoding="utf-8")
            full_zip = Path(shutil.make_archive(
                str(full_base) + "_metadata_only", "zip",
                root_dir=metadata_dir))
            evidence_included = False
        return {
            "bundle_path": str(full_zip),
            "bundle_bytes": full_zip.stat().st_size,
            "maximum_bytes": int(maximum_bytes),
            "evidence_included": evidence_included,
            "omitted_evidence": omitted,
        }


def open_support_email_draft(bundle: dict, report_id: str) -> None:
    """Open a pre-addressed draft and reveal the bundle for manual attachment."""
    subject = f"{SUPPORT_SUBJECT_PREFIX} {report_id}"
    body = (
        f"AGVG Lab Tools issue report {report_id}\n\n"
        "Please attach the support bundle shown in the opened folder:\n"
        f"{bundle['bundle_path']}\n\n"
        "The bundle was prepared locally and will not be transmitted until "
        "you send this email.")
    uri = (
        f"mailto:{SUPPORT_EMAIL}?subject={quote(subject)}&body={quote(body)}")
    try:
        os.startfile(uri)
    except AttributeError:
        subprocess.Popen(["cmd", "/c", "start", "", uri])
    try:
        os.startfile(str(Path(bundle["bundle_path"]).parent))
    except Exception:
        pass


def show_first_run_briefing(
    briefing: ToolBriefing, *, parent=None,
    store: RunFeedbackStore | None = None,
) -> bool:
    """Show once per tool version. Return False when the user cancels launch."""
    from tkinter import messagebox
    store = store or RunFeedbackStore()
    if not store.needs_briefing(briefing):
        return True
    proceed = messagebox.askokcancel(
        f"Before first use: {briefing.tool_name}", briefing.text(),
        parent=parent)
    if proceed:
        store.acknowledge(briefing)
    return proceed


def prompt_post_run_feedback(
    *, tool_name: str, tool_version: str, run_id: str,
    acquisition: AcquisitionMetadata, parameters: dict,
    parent=None, evidence_paths=None, roi_coordinates=None,
    frame_index=None, store: RunFeedbackStore | None = None,
) -> str:
    """Prompt clean versus issue, then capture a categorized issue report."""
    from tkinter import messagebox, simpledialog
    store = store or RunFeedbackStore()
    clean = messagebox.askyesno(
        "How did this run go?",
        "Did the tool complete cleanly with no tracking, event, ROI, scale, "
        "or crash issue?", parent=parent)
    if clean:
        note = simpledialog.askstring(
            "Optional run note", "Optional note about this clean run:",
            parent=parent) or ""
        store.record_clean_run(
            tool_name=tool_name, tool_version=tool_version, run_id=run_id,
            acquisition=acquisition, parameters=parameters, note=note)
        inspected = messagebox.askyesno(
            "Reviewed automated proposals?",
            "Did you inspect at least one automated frame or event?",
            parent=parent)
        if inspected:
            agreed = messagebox.askyesno(
                "Review result",
                "Did the inspected automated result agree with your review?",
                parent=parent)
            store.record_review(
                tool_name=tool_name, tool_version=tool_version,
                run_id=run_id, agreed=agreed, condition=parameters,
                note=note)
        return "clean"
    category = simpledialog.askstring(
        "Issue category",
        "Enter one category:\n" + "\n".join(sorted(FAILURE_CATEGORIES)),
        parent=parent)
    if not category:
        return "not_recorded"
    category = category.strip().lower().replace(" ", "_")
    if category not in FAILURE_CATEGORIES:
        messagebox.showerror(
            "Issue not recorded", "The category was not recognized.",
            parent=parent)
        return "not_recorded"
    note = simpledialog.askstring(
        "What happened?", "Describe what went wrong and what you expected:",
        parent=parent) or ""
    severity = simpledialog.askinteger(
        "Severity", "Severity from 1 (minor) to 5 (silent wrong answer):",
        minvalue=1, maxvalue=5, parent=parent) or 1
    selected_evidence = evidence_paths
    if evidence_paths:
        include_visuals = messagebox.askyesno(
            "Include diagnostic evidence?",
            "Include the listed screenshots, clips, or result files in the "
            "local failure report?\n\nNo files leave this computer unless you "
            "separately choose to prepare and send an email.",
            parent=parent)
        if not include_visuals:
            selected_evidence = None
    report = store.record_issue(
        tool_name=tool_name, tool_version=tool_version, run_id=run_id,
        acquisition=acquisition, category=category, parameters=parameters,
        user_note=note, severity=severity, roi_coordinates=roi_coordinates,
        frame_index=frame_index, evidence_paths=selected_evidence)
    messagebox.showinfo(
        "Issue recorded", f"Saved locally to:\n{report}", parent=parent)
    if messagebox.askyesno(
            "Send feedback to the AGVG Lab?",
            f"Prepare a support bundle and open an email draft addressed to "
            f"{SUPPORT_EMAIL}?\n\nThe email will not be sent automatically.",
            parent=parent):
        bundle = store.prepare_support_bundle(report)
        open_support_email_draft(bundle, report.name)
        if not bundle["evidence_included"]:
            messagebox.showwarning(
                "Metadata-only bundle",
                "The visual evidence exceeded the 18 MB support-bundle limit "
                "and remains local. A metadata/log-only bundle was prepared.",
                parent=parent)
    return "issue"
