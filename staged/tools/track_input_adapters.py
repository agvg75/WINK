"""Adapters from existing Track-one-worm/Kinematics CSVs to Tier-3 consumers.

These functions do not track images. They preserve the reviewed upstream
identity and expose any biological threshold used to derive an event.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


def _base(table: pd.DataFrame, source: str | Path) -> pd.DataFrame:
    out = table.copy()
    if "time_s" not in out and {"frame", "fps"} <= set(out):
        out["time_s"] = out["frame"] / out["fps"]
    if "worm_id" not in out:
        out["worm_id"] = out.get("animal_id", "worm_1")
    if "plate_id" not in out:
        fallback = Path(source).stem
        out["plate_id"] = out.get("condition", fallback)
    return out


def adapt_existing_track_csv(table: pd.DataFrame, assay: str, source: str | Path,
                             *, reversal_velocity_threshold_um_s: float = 0.0,
                             omega_curvature_threshold_deg: float = 100.0
                             ) -> pd.DataFrame:
    """Return the established consumer schema, or the input unchanged if ready."""
    out = _base(table, source)
    if assay in {"roaming_dwelling", "quiescence"}:
        if "speed_um_s" not in out:
            if "axial_vel_px_s" in out:
                scale = out["um_per_px"] if "um_per_px" in out else 1.0
                out["speed_um_s"] = np.abs(out["axial_vel_px_s"] * scale)
            elif {"x", "y"} <= set(out):
                dt = out.groupby(["plate_id", "worm_id"])["time_s"].diff()
                dx = out.groupby(["plate_id", "worm_id"])["x"].diff()
                dy = out.groupby(["plate_id", "worm_id"])["y"].diff()
                out["speed_um_s"] = np.hypot(dx, dy) / dt
        if assay == "roaming_dwelling" and "angular_velocity_deg_s" not in out:
            if "angular_vel_deg_s" in out:
                out["angular_velocity_deg_s"] = out["angular_vel_deg_s"]
            elif "seg_angle_deg" in out:
                out["angular_velocity_deg_s"] = (
                    out.groupby(["plate_id", "worm_id"])["seg_angle_deg"].diff() /
                    out.groupby(["plate_id", "worm_id"])["time_s"].diff())
    elif assay == "search" and "event_type" not in out:
        velocity = out.get("axial_vel_um_s")
        if velocity is None and "axial_vel_px_s" in out:
            velocity = out["axial_vel_px_s"] * out.get("um_per_px", 1.0)
        curvature = out.get("seg_curv_deg", pd.Series(0.0, index=out.index))
        reversal = velocity < reversal_velocity_threshold_um_s
        omega = curvature.abs() >= omega_curvature_threshold_deg
        out["event_type"] = np.select(
            [omega, reversal], ["omega", "reversal"], default="none")
        out["observable_duration_s"] = (
            out["time_s"].max() - out["time_s"].min())
        out["event_derivation"] = (
            f"review required; reversal velocity < "
            f"{reversal_velocity_threshold_um_s:g} um/s; |curvature| >= "
            f"{omega_curvature_threshold_deg:g} deg")
    return out

