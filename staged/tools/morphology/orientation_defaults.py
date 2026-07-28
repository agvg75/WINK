"""Persistent image-orientation defaults for morphology tools.

Defaults reduce repeated student input but never remove provenance: each image
export must record whether the saved orientation was reused or changed.
"""
from __future__ import annotations
import json,os
from pathlib import Path

VALID_AP={"left_to_right","right_to_left"}
VALID_DV={"dorsal_up","dorsal_down"}

def settings_path():
    base=Path(os.environ.get("APPDATA",Path.home()))/"AGVGLab"
    return base/"morphology_orientation_defaults.json"

def factory_defaults():
    return {"anterior_posterior":"left_to_right","dorsal_ventral":"dorsal_up",
            "source":"factory_default","confirmed":False}

def load_defaults(path=None):
    p=Path(path) if path else settings_path()
    if not p.exists():return factory_defaults()
    try:d=json.loads(p.read_text(encoding="utf-8"))
    except Exception:return factory_defaults()
    if d.get("anterior_posterior") not in VALID_AP or d.get("dorsal_ventral") not in VALID_DV:return factory_defaults()
    return d

def save_defaults(anterior_posterior,dorsal_ventral,path=None):
    if anterior_posterior not in VALID_AP:raise ValueError("Invalid anterior/posterior direction")
    if dorsal_ventral not in VALID_DV:raise ValueError("Invalid dorsal/ventral direction")
    p=Path(path) if path else settings_path();p.parent.mkdir(parents=True,exist_ok=True)
    d={"anterior_posterior":anterior_posterior,"dorsal_ventral":dorsal_ventral,
       "source":"user_saved_default","confirmed":True}
    p.write_text(json.dumps(d,indent=2),encoding="utf-8");return d

def image_orientation(defaults,ap=None,dv=None):
    """Create per-image provenance without silently changing saved defaults."""
    used_ap=ap or defaults["anterior_posterior"];used_dv=dv or defaults["dorsal_ventral"]
    if used_ap not in VALID_AP or used_dv not in VALID_DV:raise ValueError("Invalid image orientation")
    changed=(used_ap!=defaults["anterior_posterior"] or used_dv!=defaults["dorsal_ventral"])
    return {"anterior_posterior":used_ap,"dorsal_ventral":used_dv,
            "orientation_source":"changed_for_this_image" if changed else "reused_saved_default",
            "saved_default_ap":defaults["anterior_posterior"],"saved_default_dv":defaults["dorsal_ventral"]}

