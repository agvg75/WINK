"""The Help button inside WINK, and the client that talks to the lab endpoint.

The network half is deliberately separate from the Tk half so it can be tested
without a window, and so a student machine needs nothing beyond the standard
library - urllib, not requests. WINK is installed on lab PCs by a batch file;
every extra dependency is another thing that fails on one machine and not
another.

WHAT THE PANEL IS FOR, and what it must not become. It answers questions about
what a WINK tool did and why, from the tool's own recorded operating limits. It
is not a general assistant, and the endpoint refuses to guess outside that
grounding - so the honest failure mode here is "I don't have that", which is
correct and should not be papered over with a friendlier message.

THE OUTCOME BUTTONS ARE NOT POLITENESS. They are what makes an answer available
to the next student, and what removes it if it was wrong. An answer nobody
confirmed is never served from the ledger; one student saying it did not help
demotes it however many it satisfied. Without them the ledger accumulates
unverified text and starts handing it out.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(os.environ.get(
    "WINK_ASSISTANT_CONFIG",
    Path(os.environ.get("LOCALAPPDATA", ".")) / "LabTools"
    / "wink_assistant_client.json"))

TIMEOUT_S = 45


class AssistantUnavailable(Exception):
    """Not an error in the analysis - the helper is simply not reachable."""


def load_config():
    """{'endpoint': 'http://10.2.3.163:5000', 'token': 'wink-...'} or None."""
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise AssistantUnavailable(
            f"{CONFIG_PATH} is not valid JSON ({exc}). Ask Andres to re-issue "
            f"it; nothing else in WINK is affected.")
    if not cfg.get("endpoint") or not cfg.get("token"):
        raise AssistantUnavailable(
            f"{CONFIG_PATH} is missing the endpoint or the token. Ask Andres "
            f"for your token - it identifies you for the daily limit.")
    return cfg


def _post(url, payload, token):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-WINK-Token": token},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"error": f"HTTP {exc.code}"}
    except urllib.error.URLError as exc:
        # The commonest case by far, and worth naming precisely: the lab PC
        # that answers questions is simply switched off. That is not a fault
        # in the student's analysis and should not read like one.
        raise AssistantUnavailable(
            f"Could not reach the lab assistant at {url}. The PC that answers "
            f"questions may be switched off, or you may be off the campus "
            f"network. Nothing about your analysis is affected - carry on and "
            f"try again later.  ({exc.reason})")


def ask(question, tool, config=None):
    """Ask about one tool. Returns the response body plus the HTTP status."""
    cfg = config or load_config()
    if cfg is None:
        raise AssistantUnavailable(
            "The assistant is not set up on this machine. Ask Andres for a "
            "token; WINK works exactly as before without it.")
    code, body = _post(f"{cfg['endpoint'].rstrip('/')}/ask",
                       {"question": question, "tool": tool}, cfg["token"])
    body["_status"] = code
    return body


def report_outcome(interaction_id, outcome, config=None):
    """Tell the ledger whether the answer helped. 'resolved' | 'did_not_help'."""
    cfg = config or load_config()
    if cfg is None:
        raise AssistantUnavailable("The assistant is not set up.")
    code, body = _post(f"{cfg['endpoint'].rstrip('/')}/outcome",
                       {"interaction_id": interaction_id, "outcome": outcome},
                       cfg["token"])
    body["_status"] = code
    return body


def write_config(endpoint, token, path=None):
    """Write a student's config. Used by the setup helper, not by the panel."""
    p = Path(path or CONFIG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"endpoint": endpoint, "token": token}, indent=2),
                 encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #
def open_panel(parent, tool_key, tool_label=None):
    """A small ask-and-answer window over `parent`, scoped to one tool."""
    import threading
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(parent)
    win.title(f"WINK help - {tool_label or tool_key}")
    win.geometry("560x460")

    ttk.Label(win, text=f"Ask about: {tool_label or tool_key}",
              font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 2))
    ttk.Label(win, wraplength=520, foreground="#555",
              text=("Answers come from this tool's recorded operating limits. "
                    "If it says it does not know, that is honest - ask "
                    "Andres.")).pack(anchor="w", padx=12)

    entry = tk.Text(win, height=4, wrap="word")
    entry.pack(fill="x", padx=12, pady=8)
    entry.focus_set()

    out = tk.Text(win, wrap="word", state="disabled", background="#f7f7f7")
    out.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(0, 12))
    ask_btn = ttk.Button(bar, text="Ask")
    ask_btn.pack(side="left")
    state = {"interaction_id": None}

    def show(text):
        out.configure(state="normal")
        out.delete("1.0", "end")
        out.insert("1.0", text)
        out.configure(state="disabled")

    def set_outcome(kind):
        if state["interaction_id"] is None:
            return
        try:
            report_outcome(state["interaction_id"], kind)
            resolved.state(["disabled"])
            unhelpful.state(["disabled"])
            show(out.get("1.0", "end").rstrip()
                 + ("\n\n[Recorded as resolved - this answer can now help the "
                    "next student.]" if kind == "resolved" else
                    "\n\n[Recorded as not helpful - it will not be offered to "
                    "anyone else.]"))
        except AssistantUnavailable as exc:
            show(f"{out.get('1.0', 'end').rstrip()}\n\n[Could not record that: "
                 f"{exc}]")

    resolved = ttk.Button(bar, text="This resolved it",
                          command=lambda: set_outcome("resolved"))
    unhelpful = ttk.Button(bar, text="Didn't help",
                           command=lambda: set_outcome("did_not_help"))
    resolved.pack(side="right")
    unhelpful.pack(side="right", padx=(0, 6))
    resolved.state(["disabled"])
    unhelpful.state(["disabled"])

    def run():
        q = entry.get("1.0", "end").strip()
        if not q:
            return
        ask_btn.state(["disabled"])
        show("Asking...")

        def work():
            try:
                body = ask(q, tool_key)
            except AssistantUnavailable as exc:
                win.after(0, lambda: (show(str(exc)), ask_btn.state(["!disabled"])))
                return

            def done():
                ask_btn.state(["!disabled"])
                if body.get("answer"):
                    # Provenance ABOVE the answer, not appended as a footnote:
                    # whether anyone has checked it changes how the answer
                    # should be read, so it belongs before it is read.
                    parts = [body.get("provenance", ""), "", body["answer"]]
                    if body.get("quota_warning"):
                        parts += ["", f"[{body['quota_warning']}]"]
                    show("\n".join(p for p in parts if p is not None).strip())
                    state["interaction_id"] = body.get("interaction_id")
                    resolved.state(["!disabled"])
                    unhelpful.state(["!disabled"])
                else:
                    show(body.get("error", "No answer was returned."))
            win.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    ask_btn.configure(command=run)
    entry.bind("<Control-Return>", lambda _e: run())
    return win


def add_help_button(parent, tool_key, tool_label=None, **pack_kw):
    """Put a Help button on a tool's toolbar. Silent no-op if Tk is absent."""
    try:
        from tkinter import ttk
    except ImportError:                                    # pragma: no cover
        return None
    btn = ttk.Button(parent, text="Help",
                     command=lambda: open_panel(parent, tool_key, tool_label))
    btn.pack(**pack_kw) if pack_kw else btn.pack(side="right")
    return btn
