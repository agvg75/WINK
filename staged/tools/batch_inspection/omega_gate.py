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

THE CHECKBOX IS UNCHECKED BY DEFAULT, which matches this lab's RGBCaMP
workflow: students are instructed to analyse forward crawling and reversing
only, so the common case really is "no omegas" and making them tick a box every
time would be friction that teaches people to tick without looking.

BUT LEFT-AT-DEFAULT IS RECORDED SEPARATELY FROM CONFIRMED. Whether a person
actually looked is a different fact from what the box says, and only one of
them is evidence. `confirmed` is true only when someone set the box
deliberately; a recording processed without anyone touching it carries
`confirmed: false`, so a later reader can tell a checked assertion from an
untouched default.

THIS DEFAULT IS SAFE FOR RGBCaMP AND WRONG FOR GCaMP-ONLY DATA, which does
contain omegas and coiling. The default belongs to the acquisition, not to the
software, which is why it is a parameter here rather than a constant.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

ANSWERS = ("no_omegas", "contains_omegas", "unknown")

# Unchecked = no omegas, per the RGBCaMP workflow. A tool whose
# recordings DO contain omegas should pass default_contains=True.
DEFAULT_CONTAINS_OMEGAS = False


class OmegaGateError(Exception):
    """Refusals that name the consequence."""


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
            "unknown": ("Nobody answered. Treated exactly as "
                        "'contains_omegas', because the failure that would "
                        "cause is silent and the one it prevents is visible."),
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
    if not doc.get("asked"):
        doc["answer"] = "contains_omegas" if default_contains else "no_omegas"
    ok = doc.get("answer") == "no_omegas"
    return {
        "allowed": bool(ok),
        "answer": doc.get("answer", "unknown"),
        "asked": bool(doc.get("asked")),
        "confirmed": bool(doc.get("confirmed", False)),
        "from_default": not bool(doc.get("asked")),
        "why": (
            "Confirmed free of omegas, so any profile inversion is a tracker "
            "artefact and can be corrected without review."
            if ok else
            f"Answer is {doc.get('answer', 'unknown')!r}. Automatic correction "
            f"is refused because a real reorientation here would be silently "
            f"reversed - the animal turns, the profile inverts, and the tool "
            f"would call the biology an error."),
        "fallback": (None if ok else
                     "Use the duration test: an event clearing one undulation "
                     "period with a genuine curvature spike is a candidate "
                     "real turn and goes to a person."),
    }


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

    # A CHECKBOX, unchecked by default. Ticking it says omegas are present.
    contains = tk.BooleanVar(value=bool(DEFAULT_CONTAINS_OMEGAS))
    ttk.Checkbutton(bar, variable=contains,
                    text="This recording contains omegas or coiling"
                    ).pack(side="left")

    def done():
        a = "contains_omegas" if contains.get() else "no_omegas"
        state["answer"] = a
        # touched=True only if the box was moved off its default, or OK was
        # pressed - closing the window is not a confirmation.
        record(recording, a, frames_viewed=state["viewed"],
               confirmed=state.get("touched", True))
        if on_answer:
            on_answer(a)
        win.destroy()

    def closed():
        state["answer"] = "no_omegas" if not contains.get() else "contains_omegas"
        record(recording, state["answer"], frames_viewed=state["viewed"],
               confirmed=False)
        win.destroy()

    ttk.Button(bar, text="OK", command=done).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", closed)
    return win, state
