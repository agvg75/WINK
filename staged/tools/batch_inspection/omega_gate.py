"""Ask at load time whether this recording contains omegas, and let them look.

Andres's design, and it is better than a configuration flag. Whether a
recording contains omega bends is a fact about THAT recording, not about the
dataset or the protocol, and the person loading it can answer by looking. So
the question is asked once at load, with a scrubber to answer it.

WHY IT MATTERS, and it is not a detail. The automatic label-flip correction is
only safe where a real reorientation cannot occur. In this lab's RGBCaMP
recordings students analyse forward crawling and reversing only, because omegas
cannot be analysed well yet - so every profile inversion there is a tracker
artefact by construction. Point the same correction at recordings that DO
contain omegas and it silently reverses real turns: the animal genuinely
reorients, the profile genuinely inverts, and the tool corrects biology into an
artefact with nothing downstream to reveal it.

A REVERSAL IS NOT AN OMEGA and does not threaten the correction. Backing up
changes the direction the wave travels while the head stays the head. It leaves
a different signature entirely and is detected separately.

THREE ANSWERS, NOT TWO, per Andres: yes, no, and left blank meaning not
inspected. A checkbox cannot express the third, and that is exactly the state
most recordings are in - it collapses "I looked and there are none" into the
same tick as "I never opened this", and those are different facts about the
data. The menu starts blank, so the honest state is the resting state and a
person has to do something to make a claim.

LEFT BLANK STILL FOLLOWS THE WORKFLOW DEFAULT rather than blocking. Students
here are instructed to analyse forward crawling and reversing only, so "no
omegas" is a real if weak piece of evidence - it comes from the protocol rather
than from this recording. Refusing every uninspected file would stop a 24-file
batch twenty-four times and teach people to answer without looking, which is
the failure the third state exists to prevent.

WHAT MAKES THAT SAFE IS THAT IT IS COUNTED. `batch_summary` reports how many
recordings were auto-corrected on an unconfirmed default, so "19 of 24 were
corrected without anyone looking" is visible once, in aggregate, instead of
being invisible in nineteen separate sidecars.

THIS DEFAULT IS SAFE FOR RGBCaMP AND WRONG FOR GCaMP-ONLY DATA, which does
contain omegas and coiling. The default belongs to the acquisition, not to the
software, which is why it is a parameter here rather than a constant.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

ANSWERS = ("no_omegas", "contains_omegas", "unknown")

# What the three menu entries say, in the order they appear. Blank is first
# because it is the resting state and should not look like a third opinion
# tucked under two real ones.
MENU = (("", "unknown", "not inspected"),
        ("No", "no_omegas", "forward crawling and reversing only"),
        ("Yes", "contains_omegas", "the animal turns around or coils"))

# Blank falls to this, per the RGBCaMP workflow. A tool whose recordings DO
# contain omegas should pass default_contains=True.
DEFAULT_CONTAINS_OMEGAS = False


class OmegaGateError(Exception):
    """Refusals that name the consequence."""


def _who():
    """Initials of whoever is at this station, or "" - never a guess."""
    try:
        import sys
        app = str(Path(__file__).resolve().parents[2] / "app")
        if app not in sys.path:
            sys.path.insert(0, app)
        import operator_identity
        return operator_identity.initials()
    except Exception:
        return ""


def gate_path(recording):
    return Path(str(recording)).with_suffix(".omega_gate.json")


def load(recording):
    try:
        return json.loads(gate_path(recording).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"recording": str(recording), "answer": "unknown",
                "asked": False}
    except json.JSONDecodeError as exc:
        raise OmegaGateError(
            f"{gate_path(recording)} is not valid JSON ({exc}). Treating an "
            f"unreadable gate as an answer would let a correction run on data "
            f"nobody vouched for.")


def record(recording, answer, by="", frames_viewed=0, note="",
           confirmed=True):
    if answer not in ANSWERS:
        raise OmegaGateError(
            f"{answer!r} is not one of {ANSWERS}. An invented answer would "
            f"gate a correction that silently reverses real reorientations.")
    # "Not inspected" can never be confirmed - that is what the word means.
    # Without this, a caller could write an uninspected recording down as a
    # deliberate assertion and the aggregate count would under-report.
    if answer == "unknown":
        confirmed = False
    if not by:
        by = _who()
    doc = {
        "recording": str(recording), "answer": answer, "asked": True,
        "answered_by": by, "answered_utc": _dt.datetime.now(
            _dt.timezone.utc).isoformat(),
        "frames_viewed": int(frames_viewed),
        "confirmed": bool(confirmed),
        "note": note,
        "confirmation_note": (
            "A person set this deliberately." if confirmed else
            "LEFT AT THE DEFAULT - nobody asserted this. The value is the "
            "workflow's assumption, not evidence about this recording."),
        "means": {
            "no_omegas": ("The person confirmed this recording holds only "
                          "forward crawling and reversing. Every profile "
                          "inversion is therefore a tracker artefact and can "
                          "be corrected automatically."),
            "contains_omegas": ("Real reorientations occur here, so an "
                                "inversion may be the animal. Corrections go "
                                "to review, never automatic."),
            "unknown": ("NOT INSPECTED. Nobody looked at this recording, so "
                        "it falls to the workflow default - which is evidence "
                        "about the protocol, not about this file. Counted in "
                        "the batch summary so the size of that gap is visible "
                        "in aggregate rather than buried per-file."),
        }[answer],
    }
    gate_path(recording).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def may_autocorrect(recording, default_contains=DEFAULT_CONTAINS_OMEGAS):
    """Is automatic label-flip correction permitted for this recording?

    An unasked recording follows `default_contains`, which is False for the
    RGBCaMP workflow and must be set True for data that contains omegas.
    """
    doc = load(recording)
    stated = doc.get("answer", "unknown")
    # Never inspected and explicitly left blank are the SAME evidentiary state:
    # nobody looked. Both fall to the workflow default; neither is confirmed.
    uninspected = stated == "unknown" or not doc.get("asked")
    effective = (("contains_omegas" if default_contains else "no_omegas")
                 if uninspected else stated)
    ok = effective == "no_omegas"
    return {
        "allowed": bool(ok),
        "answer": effective,
        "stated": stated,
        "asked": bool(doc.get("asked")),
        "inspected": not uninspected,
        "confirmed": bool(doc.get("confirmed", False)) and not uninspected,
        "from_default": bool(uninspected),
        "why": (
            ("Confirmed free of omegas, so any profile inversion is a tracker "
             "artefact and can be corrected without review."
             if not uninspected else
             "NOT INSPECTED - permitted by the workflow default, which says "
             "these recordings hold forward crawling and reversing only. That "
             "is evidence about the protocol, not about this file. Counted in "
             "the batch summary.")
            if ok else
            (f"Answer is {effective!r}. Automatic correction is refused "
             f"because a real reorientation here would be silently reversed - "
             f"the animal turns, the profile inverts, and the tool would call "
             f"the biology an error.")),
        "fallback": (None if ok else
                     "Use the duration test: an event clearing one undulation "
                     "period with a genuine curvature spike is a candidate "
                     "real turn and goes to a person."),
    }


def batch_summary(recordings, default_contains=DEFAULT_CONTAINS_OMEGAS):
    """How much of a batch was corrected on nobody's word.

    This is the safety valve for letting blank follow the default. A per-file
    sidecar saying "not inspected" is true and invisible; "19 of 24 recordings
    were auto-corrected without anyone looking" is the same fact in the one
    form that provokes a decision.
    """
    gates = [(r, may_autocorrect(r, default_contains)) for r in recordings]
    auto = [r for r, g in gates if g["allowed"]]
    unseen = [r for r, g in gates if g["allowed"] and not g["inspected"]]
    refused = [r for r, g in gates if not g["allowed"]]
    n = max(len(gates), 1)
    out = {
        "n_recordings": len(gates),
        "auto_corrected": len(auto),
        "auto_corrected_uninspected": len(unseen),
        "refused_to_review": len(refused),
        "inspected_fraction": round(1 - len(unseen) / n, 3),
        "uninspected_files": [str(r) for r in unseen],
        "operator": _who() or None,
    }
    if unseen:
        out["headline"] = (
            f"{len(unseen)} of {len(gates)} recordings were auto-corrected "
            f"without anyone confirming they contain no omegas. The default "
            f"is the RGBCaMP protocol, not an observation about these files. "
            f"Spot-check a few before the numbers leave this session.")
    else:
        out["headline"] = (
            f"All {len(auto)} auto-corrected recordings were inspected first.")
    return out


def biological_floor(fps, undulation_hz=0.2):
    """Frames one undulation takes - the shortest a real reorientation can be.

    A reorientation needs an omega bend, which is at least one full wave. At
    5 fps and 0.2 Hz crawling that is 25 frames; the longest artefact measured
    across this archive was 6.
    """
    if not fps or not undulation_hz:
        raise OmegaGateError(
            "Both fps and undulation frequency are needed. Guessing either "
            "would set the threshold that decides whether an event is biology.")
    return float(fps) / float(undulation_hz)


# --------------------------------------------------------------------------- #
# The dialog
# --------------------------------------------------------------------------- #
def ask(parent, recording, frames=None, fps=None, on_answer=None):
    """The load-time question, with a scrubber so it can be answered by looking.

    `frames` is a sequence of image paths or arrays. Without it the question is
    still asked, but the person has nothing to check against and the dialog
    says so rather than implying they have looked.
    """
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(parent)
    win.title("Does this recording contain omegas?")
    win.transient(parent)
    state = {"answer": "unknown", "viewed": 0}

    ttk.Label(win, text="Does this recording contain omega bends or coiling?",
              font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14,
                                                  pady=(14, 4))
    ttk.Label(win, wraplength=560, foreground="#444", justify="left",
              text=("If it holds only forward crawling and reversing, label "
                    "flips can be corrected automatically - they are tracker "
                    "artefacts. If the animal really turns around, an "
                    "inversion may be the animal, and correcting it would "
                    "reverse real biology.\n\n"
                    "A reversal is NOT an omega: backing up keeps the head as "
                    "the head.")).pack(anchor="w", padx=14)

    canvas_holder = ttk.Frame(win)
    canvas_holder.pack(fill="both", expand=True, padx=14, pady=8)

    if frames:
        import numpy as np
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        fig = Figure(figsize=(4.2, 3.2))
        ax = fig.add_subplot(111)
        ax.set_xticks([]); ax.set_yticks([])
        canvas = FigureCanvasTkAgg(fig, master=canvas_holder)
        canvas.get_tk_widget().pack(fill="both", expand=True)

        def _img(i):
            f = frames[int(i)]
            if isinstance(f, (str, Path)):
                import montage as mo
                return mo._read(f)
            return np.asarray(f)

        im = ax.imshow(_img(0), cmap="gray")
        ax.set_title("frame 0", fontsize=9)

        var = tk.IntVar(value=0)

        def scrub(_v=None):
            i = var.get()
            im.set_data(_img(i))
            im.autoscale()
            ax.set_title(f"frame {i}" + (f"   {i / fps:.1f} s" if fps else ""),
                         fontsize=9)
            state["viewed"] = max(state["viewed"], i)
            canvas.draw_idle()

        ttk.Scale(win, from_=0, to=len(frames) - 1, variable=var,
                  command=scrub, orient="horizontal").pack(fill="x", padx=14)
        ttk.Label(win, text="Drag to scrub through the recording.",
                  foreground="#666").pack(anchor="w", padx=14)
    else:
        ttk.Label(canvas_holder, foreground="#B03030", wraplength=560,
                  text=("No frames were supplied, so this cannot be checked "
                        "by looking. Answer only if you already know the "
                        "recording.")).pack(anchor="w")

    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=14, pady=12)

    def answer(a):
        def go():
            state["answer"] = a
            record(recording, a, frames_viewed=state["viewed"])
            if on_answer:
                on_answer(a)
            win.destroy()
        return go

    # THREE STATES, starting blank. Blank is not a third opinion - it is the
    # absence of one, and it is the honest resting state for a recording
    # nobody has scrubbed through.
    labels = [lbl for lbl, _key, _hint in MENU]
    hints = {lbl: hint for lbl, _key, hint in MENU}
    keys = {lbl: key for lbl, key, _hint in MENU}

    ttk.Label(bar, text="Contains omegas:").pack(side="left")
    choice = tk.StringVar(value="")
    combo = ttk.Combobox(bar, textvariable=choice, values=labels,
                         state="readonly", width=6)
    combo.pack(side="left", padx=(6, 8))

    hint = ttk.Label(bar, foreground="#666", text=hints[""])
    hint.pack(side="left")

    def touched(_e=None):
        state["touched"] = True
        hint.configure(text=hints.get(choice.get(), ""))
    combo.bind("<<ComboboxSelected>>", touched)

    def commit(confirmed):
        a = keys.get(choice.get(), "unknown")
        state["answer"] = a
        record(recording, a, frames_viewed=state["viewed"],
               confirmed=bool(confirmed) and a != "unknown")
        if on_answer:
            on_answer(a)
        win.destroy()

    # Pressing OK on a blank menu is still not an assertion - `record` forces
    # confirmed=False for "unknown", so the button cannot manufacture evidence.
    ttk.Button(bar, text="OK",
               command=lambda: commit(state.get("touched", False))
               ).pack(side="right")
    # Closing the window is never a confirmation, whatever the menu shows.
    win.protocol("WM_DELETE_WINDOW", lambda: commit(False))
    return win, state
