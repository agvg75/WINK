"""S3: local-first structured failure capture and reproducibility triage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from acquisition import AcquisitionMetadata


FAILURE_CATEGORIES = {
    "tracked_wrong_object", "lost_identity", "false_event", "missed_event",
    "roi_drift", "wrong_scale", "crash",
}
SILENT_WRONG = {
    "tracked_wrong_object", "lost_identity", "false_event", "missed_event",
    "roi_drift", "wrong_scale",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class FailureContext:
    tool_name: str
    tool_version: str
    acquisition: AcquisitionMetadata
    category: str
    roi_coordinates: object
    frame_index: int | None
    parameters: dict
    user_note: str = ""
    severity: int = 1
    classification: str = "untriaged"

    def validate(self) -> "FailureContext":
        if self.category not in FAILURE_CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(FAILURE_CATEGORIES)}")
        if not 1 <= int(self.severity) <= 5:
            raise ValueError("severity must be from 1 to 5.")
        if self.classification not in {
                "untriaged", "user_error", "tool_failure"}:
            raise ValueError("classification is not recognized.")
        self.acquisition.validate()
        return self


class FailureLibrary:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def capture(
        self,
        context: FailureContext,
        evidence_paths: list[str | Path] | None = None,
    ) -> Path:
        context.validate()
        report_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" +
            uuid.uuid4().hex[:10])
        destination = self.root / report_id
        destination.mkdir()
        evidence = []
        for source_value in evidence_paths or []:
            source = Path(source_value)
            if not source.is_file():
                continue
            target = destination / source.name
            shutil.copy2(source, target)
            evidence.append({
                "file": target.name,
                "sha256": _sha256(target),
                "bytes": target.stat().st_size,
            })
        payload = {
            "schema_version": 1,
            "report_id": report_id,
            "captured_utc": datetime.now(timezone.utc).isoformat(),
            **context.acquisition.stamped(
                context.tool_name, context.tool_version),
            "category": context.category,
            "roi_coordinates": context.roi_coordinates,
            "frame_index": context.frame_index,
            "parameters": context.parameters,
            "user_note": context.user_note,
            "severity": int(context.severity),
            "classification": context.classification,
            "evidence": evidence,
            "reproducible": None,
            "reproduction_reason": "not checked",
        }
        (destination / "report.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        return destination

    def verify_reproducible(self, report_dir: str | Path) -> tuple[bool, str]:
        directory = Path(report_dir)
        report_path = directory / "report.json"
        if not report_path.is_file():
            return False, "saved report state is missing"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        for item in payload.get("evidence", []):
            path = directory / item["file"]
            if not path.is_file():
                reason = f"saved evidence is missing: {item['file']}"
                self._write_reproduction(payload, report_path, False, reason)
                return False, reason
            if _sha256(path) != item["sha256"]:
                reason = f"saved evidence hash mismatch: {item['file']}"
                self._write_reproduction(payload, report_path, False, reason)
                return False, reason
        reason = "saved state and evidence hashes are present"
        self._write_reproduction(payload, report_path, True, reason)
        return True, reason

    @staticmethod
    def _write_reproduction(
        payload: dict, report_path: Path, reproducible: bool, reason: str,
    ) -> None:
        payload["reproducible"] = reproducible
        payload["reproduction_reason"] = reason
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def ranked_backlog(self) -> list[dict]:
        rows: list[dict] = []
        frequencies: dict[str, int] = {}
        reports: list[dict] = []
        for report_path in self.root.glob("*/report.json"):
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            reports.append(payload)
            key = payload["category"]
            frequencies[key] = frequencies.get(key, 0) + 1
        for payload in reports:
            category = payload["category"]
            silent_multiplier = 2 if category in SILENT_WRONG else 1
            payload = dict(payload)
            payload["frequency"] = frequencies[category]
            payload["priority"] = (
                int(payload["severity"]) * frequencies[category] *
                silent_multiplier)
            rows.append(payload)
        return sorted(rows, key=lambda item: item["priority"], reverse=True)

    def convert_to_regression_fixture(
        self, report_dir: str | Path, fixture_root: str | Path,
    ) -> Path:
        reproducible, reason = self.verify_reproducible(report_dir)
        if not reproducible:
            raise ValueError(
                "Failure cannot become a regression fixture: " + reason)
        source = Path(report_dir)
        destination = Path(fixture_root) / source.name
        if destination.exists():
            raise FileExistsError(f"Fixture already exists: {destination}")
        shutil.copytree(source, destination)
        report = json.loads(
            (destination / "report.json").read_text(encoding="utf-8"))
        runner = {
            "schema_version": 1, "fixture_id": source.name,
            "tool_name": report["tool_name"],
            "tool_version_at_capture": report["tool_version"],
            "category": report["category"],
            "expected_state": report.get("user_note", ""),
            "parameters": report["parameters"],
            "frame_index": report["frame_index"],
            "roi_coordinates": report["roi_coordinates"],
            "validation_level": "computational_regression",
        }
        (destination / "fixture.json").write_text(
            json.dumps(runner, indent=2), encoding="utf-8")
        return destination

    def triage(self) -> list[dict]:
        """Cluster by category/tool and rank silent errors above visible crashes."""
        clusters = {}
        for report_path in self.root.glob("*/report.json"):
            row = json.loads(report_path.read_text(encoding="utf-8"))
            key = (row["tool_name"], row["category"])
            cluster = clusters.setdefault(key, {
                "tool_name": key[0], "category": key[1], "frequency": 0,
                "max_severity": 0, "classification_counts": {}})
            cluster["frequency"] += 1
            cluster["max_severity"] = max(
                cluster["max_severity"], int(row["severity"]))
            classification = row.get("classification", "untriaged")
            cluster["classification_counts"][classification] = (
                cluster["classification_counts"].get(classification, 0) + 1)
        output = []
        for cluster in clusters.values():
            silent = cluster["category"] in SILENT_WRONG
            cluster["silent_wrong_answer"] = silent
            cluster["priority"] = (
                cluster["frequency"] * cluster["max_severity"] *
                (2 if silent else 1))
            cluster["route"] = (
                "manual/documentation" if
                cluster["classification_counts"].get("user_error", 0) >=
                cluster["classification_counts"].get("tool_failure", 0)
                else "code_backlog")
            output.append(cluster)
        return sorted(
            output,
            key=lambda item: (
                item["priority"], item["silent_wrong_answer"]),
            reverse=True)
