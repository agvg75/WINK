"""Which tools have which shared affordances, and which are missing them.

Andres: "those tools should be everywhere they could help. We need an audit to
make sure our work in each module informs the other ones." This is that audit.
It turns "features are inconsistently deployed" from an impression into a
table with names in it.

WHAT IT DETECTS AND WHAT IT CANNOT. Detection is by source markers - a tool
that imports CockpitApp is on the cockpit, one that mentions install_error_
reporting has error reporting. That is reliable for ABSENCE and only suggestive
for PRESENCE: a tool can import the marker and use it badly, and the audit
cannot tell. So a gap is a finding and a tick is a lead, and the report says so
rather than implying it measured quality.

NOT EVERY TOOL NEEDS EVERY CAPABILITY, which is why `applies_to` exists. A
table-only analysis tool has no images to adjust the contrast of, and marking
it "missing brightness control" would bury the real gaps in noise. Capabilities
declare what they are relevant to, and irrelevant cells are blank rather than
red.
"""
from __future__ import annotations

import re
from pathlib import Path

# marker -> what having it means. Detection is by source text, so these are
# deliberately distinctive strings rather than general words.
CAPABILITIES = {
    "cockpit": {
        "markers": ["CockpitApp"],
        "means": "uses the shared cockpit shell: controls column, hood, help",
        "applies_to": "gui",
        "why": ("Without it a tool has its own layout, its own help, and its "
                "own idea of where the process log goes - which is how "
                "fifteen tools end up feeling like fifteen programs."),
    },
    "brightness_contrast": {
        "markers": ["Brightness/contrast", "display_limits", "_display_range"],
        "means": "view-only brightness and contrast control",
        "applies_to": "image",
        "why": ("A dim or low-contrast frame cannot be judged by eye without "
                "it, so the person either accepts what the tool proposes or "
                "abandons the recording."),
    },
    "in_tool_help": {
        "markers": ["set_help(", "self.set_help"],
        "means": "contextual step-by-step help in the hood",
        "applies_to": "gui",
        "why": ("The manual cannot answer 'what do I do next' for the step "
                "someone is actually on."),
    },
    "error_reporting": {
        "markers": ["install_error_reporting"],
        "means": "errors reported against WINK's own code, not library internals",
        "applies_to": "all",
        "why": ("Two fixes were once shipped against the wrong theory because "
                "the error named a file inside pandas."),
    },
    "review_layer": {
        "markers": ["needs_help", "ReviewWorkbench", "review_session",
                    "recompute_frame"],
        "means": "a person can inspect and correct before anything is saved",
        "applies_to": "measuring",
        "why": ("Automation without a review layer means the first time "
                "anyone sees a bad frame is in the results."),
    },
    "provenance": {
        "markers": ["provenance", "_geometry.json", "sidecar", "run_record"],
        "means": "records what was measured, how, and from what",
        "applies_to": "measuring",
        "why": "A number without provenance cannot be re-derived or defended.",
    },
    "declares_scale": {
        "markers": ["um_per_px", "um_per_pixel"],
        "means": "requires or records a declared spatial scale",
        "applies_to": "measuring",
        "why": ("A length in pixels is not a measurement, and a placeholder "
                "1.000 um/px has already reached this archive once."),
    },
    "declares_fps": {
        "markers": ["fps"],
        "means": "requires or records a declared frame rate",
        "applies_to": "temporal",
        "why": ("Every rate, period and velocity is wrong by the ratio of the "
                "assumed to the true frame rate."),
    },
    "envelope": {
        "markers": [],           # filled from assistant_context at run time
        "means": "its operating limits are recorded for the help assistant",
        "applies_to": "all",
        "why": ("Without an envelope the assistant answers from general "
                "microscopy advice, which sends a student to fix the wrong "
                "thing."),
    },
    "ask_button": {
        "markers": ["assistant_tool"],
        "means": "opts into the in-tool ask button",
        "applies_to": "gui",
        "why": "The grounding exists but the tool never offers it.",
    },
}

# How a tool is classified, which decides which capabilities apply to it.
KINDS = {
    "gui": ["tkinter", "CockpitApp", "plt.show", "ginput"],
    "image": ["imshow", "tifffile", "imread", "polygon2mask"],
    "measuring": ["def measure", "def analyze", "def analyse", "to_csv",
                  "DataFrame"],
    "temporal": ["frame", "fps"],
}


class AuditError(Exception):
    """Refusals that name the consequence."""


def classify(text):
    kinds = {"all"}
    for kind, marks in KINDS.items():
        if any(m in text for m in marks):
            kinds.add(kind)
    return kinds


def audit_file(path, envelope_keys=()):
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {"tool": p.name, "path": str(p), "error": str(exc)}
    kinds = classify(text)
    stem = p.stem.replace("_tool", "").replace("_launcher", "")
    row = {"tool": p.name, "path": str(p), "kinds": sorted(kinds),
           "lines": len(text.splitlines()), "have": {}, "missing": [],
           "not_applicable": []}
    for name, spec in CAPABILITIES.items():
        applies = spec["applies_to"] in kinds
        if name == "envelope":
            present = any(k in stem or stem in k for k in envelope_keys)
        else:
            present = any(m in text for m in spec["markers"])
        if not applies:
            row["not_applicable"].append(name)
            continue
        row["have"][name] = present
        if not present:
            row["missing"].append(name)
    row["n_missing"] = len(row["missing"])
    return row


def registered_tools(hub_path):
    """The python tools the Hub actually offers, since those are what students
    reach. A capability missing from an unregistered module costs nobody
    anything yet."""
    src = Path(hub_path).read_text(encoding="utf-8")
    return sorted(set(re.findall(r'"(tools/[^"]+\.py)"', src)))


def run(root, hub="app/lab_hub.py", follow_launchers=True):
    root = Path(root)
    try:
        import sys
        sys.path.insert(0, str(root / "app"))
        import assistant_context as ctx
        envelope_keys = tuple(ctx.known_tools())
    except Exception:
        envelope_keys = ()

    rows, missing_files = [], []
    for rel in registered_tools(root / hub):
        p = root / rel
        if not p.exists():
            missing_files.append(rel)
            continue
        # A launcher usually spawns the real tool; audit what it launches.
        if follow_launchers and "_launcher" in p.name:
            sib = p.parent / p.name.replace("_launcher", "")
            if sib.exists():
                p = sib
        rows.append(audit_file(p, envelope_keys))

    rows.sort(key=lambda r: -r.get("n_missing", 0))
    by_cap = {}
    for name in CAPABILITIES:
        applicable = [r for r in rows if name in r.get("have", {})]
        have = [r for r in applicable if r["have"][name]]
        by_cap[name] = {
            "applicable": len(applicable), "have": len(have),
            "missing": len(applicable) - len(have),
            "fraction": round(len(have) / max(len(applicable), 1), 3),
            "means": CAPABILITIES[name]["means"],
            "why": CAPABILITIES[name]["why"],
            "missing_from": [r["tool"] for r in applicable
                             if not r["have"][name]],
        }
    return {
        "root": str(root), "n_tools": len(rows),
        "unresolved_paths": missing_files,
        "tools": rows, "capabilities": by_cap,
        "detection_is_heuristic": (
            "Presence is detected from source markers, so a gap is a finding "
            "and a tick is only a lead - a tool can import a capability and "
            "use it badly, and this cannot tell. Absence is the reliable half."),
        "not_every_tool_needs_every_capability": (
            "Capabilities declare what they apply to. A table-only analysis "
            "has no image to adjust, and marking it 'missing brightness "
            "control' would bury the real gaps in noise."),
    }


def report(result, top=14):
    L = [f"{result['n_tools']} registered tools audited", ""]
    L.append(f"{'capability':22s} {'have':>6} {'missing':>8}  what it means")
    L.append("-" * 96)
    for name, c in sorted(result["capabilities"].items(),
                          key=lambda kv: kv[1]["fraction"]):
        L.append(f"{name:22s} {c['have']:3d}/{c['applicable']:<3d} "
                 f"{c['missing']:8d}  {c['means'][:52]}")
    L += ["", "TOOLS WITH THE MOST GAPS", ""]
    L.append(f"{'tool':40s} {'gaps':>5}  missing")
    L.append("-" * 96)
    for r in result["tools"][:top]:
        if not r.get("n_missing"):
            continue
        L.append(f"{r['tool'][:40]:40s} {r['n_missing']:5d}  "
                 f"{', '.join(r['missing'][:5])}")
    clean = [r for r in result["tools"] if not r.get("n_missing")]
    L += ["", f"{len(clean)} tools have every capability that applies to them"]
    if clean:
        L.append("   " + ", ".join(r["tool"] for r in clean[:8]))
    return "\n".join(L)
