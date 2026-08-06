"""
convert_gui.py
=============
A double-click window that turns any movie, stack, or image folder into ONE
clean TIFF stack that Fiji opens natively, with downsampling controls so a long
high-resolution recording does not become a 600 GB file.

No terminal, no Media Encoder, no codec guessing, no duplicate files. Pick a
source, optionally trim frames / keep every Nth / reduce resolution, choose
where to save, and it writes a single correct file (a plain ImageJ stack when
small, a BigTIFF that Fiji also opens as a virtual stack when large).

Launch by double-clicking Convert_For_Fiji.bat.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "convert_gui.log"
SOFT_LIMIT = 50 * 1024**3   # warn hard above ~50 GB


def _human_size(n) -> str:
    x = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.0f} {unit}" if unit == "bytes" else f"{x:.1f} {unit}"
        x /= 1024


def _run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import movie_reader
    import convert_for_fiji as C

    root = tk.Tk()
    try:                      # error reporting
        from process_ui import install_error_reporting
        install_error_reporting(root)
    except Exception as _e:   # never break the tool for this
        print('error reporting unavailable:', _e)
    root.title("Convert for Fiji")
    root.geometry("640x560")

    state = {"src": None, "meta": None, "progress": (0, 0),
             "done": None, "error": None, "cancel": None}

    ttk.Label(root, text="Make a Fiji-ready copy of a movie",
              font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    ttk.Label(root, text="Pick a source, optionally shrink it below, then convert. "
                         "It writes one clean TIFF stack Fiji opens directly.",
              font=("Segoe UI", 9), wraplength=600, justify="left").pack(anchor="w", padx=14)

    info = tk.Text(root, height=6, width=72, wrap="word", font=("Consolas", 10),
                   state="disabled", bd=1, relief="solid")

    # downsampling options
    opt = ttk.LabelFrame(root, text="Shrink (optional): use these for long or large recordings")
    start_var = tk.StringVar(value="0")
    stop_var = tk.StringVar(value="")
    step_var = tk.StringVar(value="1")
    scale_var = tk.StringVar(value="100")
    grid = ttk.Frame(opt); grid.pack(fill="x", padx=8, pady=6)
    def _cell(col, label, var, width=7):
        ttk.Label(grid, text=label, font=("Segoe UI", 9)).grid(row=0, column=col*2, sticky="w", padx=(4, 2))
        e = ttk.Entry(grid, textvariable=var, width=width); e.grid(row=0, column=col*2+1, padx=(0, 10))
        return e
    _cell(0, "Start frame", start_var)
    _cell(1, "End frame (blank=all)", stop_var)
    _cell(2, "Keep every Nth", step_var)
    _cell(3, "Resolution %", scale_var)
    est_lbl = ttk.Label(opt, text="", font=("Segoe UI", 9, "bold"))
    est_lbl.pack(anchor="w", padx=10, pady=(0, 6))

    convert_btn = ttk.Button(root, text="Convert to Fiji TIFF", state="disabled")
    prog = ttk.Progressbar(root, mode="determinate", length=580)
    prog_lbl = ttk.Label(root, text="", font=("Segoe UI", 9))
    cancel_btn = ttk.Button(root, text="Cancel")

    def _set_info(text):
        info.config(state="normal"); info.delete("1.0", "end")
        info.insert("1.0", text); info.config(state="disabled")

    def _parse_opts():
        def _int(v, d):
            try:
                return max(0, int(float(v)))
            except Exception:
                return d
        start = _int(start_var.get(), 0)
        s = stop_var.get().strip()
        stop = None if s == "" else _int(s, None)
        step = max(1, _int(step_var.get(), 1))
        try:
            scale = float(scale_var.get()) / 100.0
        except Exception:
            scale = 1.0
        scale = min(max(scale, 0.05), 1.0)
        return start, stop, step, scale

    def _recompute(*_a):
        meta = state.get("meta")
        if not meta:
            est_lbl.config(text=""); return
        n, h, w, ch, it, fps = meta
        start, stop, step, scale = _parse_opts()
        est = C.estimate_bytes(n, h, w, ch, it, start, stop, step, scale)
        neff = C._effective_counts(n, h, w, start, stop, step, scale)[0]
        weff, heff = max(1, round(w * scale)), max(1, round(h * scale))
        big = est >= SOFT_LIMIT
        est_lbl.config(
            text=f"Output: {neff} frames, {weff} x {heff}, about {_human_size(est)}"
                 + ("   VERY LARGE, shrink more" if big else ""),
            foreground="#b00020" if big else "#0a7d33")

    for v in (start_var, stop_var, step_var, scale_var):
        v.trace_add("write", _recompute)

    def _probe(path):
        try:
            m = movie_reader.open_movie(path)
            state["meta"] = (m.n_frames, m.height, m.width, m.n_channels,
                             __import__("numpy").dtype(m.dtype).itemsize, m.fps)
            rate = f"{m.fps:g} fps" if m.fps else "frame rate not stored"
            _set_info(f"Source:    {Path(path).name}\n"
                      f"Type:      {m.source_kind}\n"
                      f"Frames:    {m.n_frames}\n"
                      f"Size:      {m.width} x {m.height}, {m.n_channels} channel(s), {m.bit_depth}-bit\n"
                      f"Frame rate:{rate}")
            m.close()
            state["src"] = path
            stop_var.set("")  # reset range to full for a new source
            convert_btn.config(state="normal")
            _recompute()
        except Exception as e:
            state["src"] = None; state["meta"] = None
            _set_info(f"Could not open this source.\n\n{e}")
            est_lbl.config(text="")
            convert_btn.config(state="disabled")

    def _pick_file():
        p = filedialog.askopenfilename(
            title="Choose a movie or stack",
            filetypes=[("Movies and stacks", "*.avi *.mp4 *.mov *.mkv *.webm *.tif *.tiff"),
                       ("All files", "*.*")])
        if p:
            _probe(p)

    def _pick_folder():
        p = filedialog.askdirectory(title="Choose a folder of image frames")
        if p:
            _probe(p)

    def _convert():
        if not state["src"]:
            return
        start, stop, step, scale = _parse_opts()
        n, h, w, ch, it, fps = state["meta"]
        est = C.estimate_bytes(n, h, w, ch, it, start, stop, step, scale)
        if est >= SOFT_LIMIT:
            if not messagebox.askyesno("Very large output",
                    f"The output will be about {_human_size(est)}. That is very large.\n\n"
                    "Consider a bigger 'Keep every Nth' or a lower 'Resolution %'. "
                    "Continue anyway?"):
                return
        default_out = C.default_output_path(state["src"])
        out = filedialog.asksaveasfilename(
            title="Save the Fiji TIFF as", defaultextension=".tif",
            initialfile=default_out.name, initialdir=str(default_out.parent),
            filetypes=[("TIFF stack", "*.tif")])
        if not out:
            return

        convert_btn.config(state="disabled")
        for b in (file_btn, folder_btn):
            b.config(state="disabled")
        prog.pack(fill="x", padx=14, pady=(4, 0))
        prog_lbl.pack(anchor="w", padx=14)
        cancel_btn.config(state="normal", text="Cancel")
        cancel_btn.pack(anchor="w", padx=14, pady=(2, 0))
        state["progress"] = (0, 0); state["done"] = None; state["error"] = None
        state["cancel"] = threading.Event()

        def _cb(done, total):
            state["progress"] = (done, total)

        def _work():
            try:
                rep = C.convert_to_tiff_stack(
                    state["src"], out, progress_cb=_cb,
                    cancel_check=lambda: state["cancel"].is_set(),
                    frame_start=start, frame_stop=stop, frame_step=step, scale=scale)
                state["done"] = rep
            except Exception:
                state["error"] = traceback.format_exc()

        threading.Thread(target=_work, daemon=True).start()
        root.after(120, _poll)

    def _do_cancel():
        ev = state.get("cancel")
        if ev is not None:
            ev.set()
        cancel_btn.config(state="disabled", text="Cancelling...")
        prog_lbl.config(text="Cancelling, please wait ...")

    def _poll():
        done, total = state["progress"]
        if total:
            prog["maximum"] = total; prog["value"] = done
            prog_lbl.config(text=f"Writing frame {done} of {total} ...")
        if state["error"] is not None:
            prog.pack_forget(); prog_lbl.pack_forget(); cancel_btn.pack_forget()
            messagebox.showerror("Conversion failed", state["error"][-1500:])
            _reenable(); return
        if state["done"] is not None:
            prog["value"] = prog["maximum"]
            rep = state["done"]
            if rep.get("aborted"):
                prog_lbl.config(text="Cancelled.")
                messagebox.showinfo("Conversion cancelled",
                                    "Conversion was cancelled. The partial file was "
                                    "removed, so nothing was saved.")
            else:
                prog_lbl.config(text="Done.")
                messagebox.showinfo("Conversion complete",
                                    f"Wrote {rep['frames_written']} frames to:\n{rep['output']}\n\n{rep['format']}")
                try:
                    os.startfile(str(Path(rep["output"]).parent))
                except Exception:
                    pass
            _reenable(); return
        root.after(120, _poll)

    def _reenable():
        prog.pack_forget(); prog_lbl.pack_forget(); cancel_btn.pack_forget()
        convert_btn.config(state="normal" if state["src"] else "disabled")
        for b in (file_btn, folder_btn):
            b.config(state="normal")

    btns = ttk.Frame(root)
    btns.pack(anchor="w", padx=14, pady=10)
    file_btn = ttk.Button(btns, text="Choose a movie or stack...", command=_pick_file)
    file_btn.pack(side="left")
    folder_btn = ttk.Button(btns, text="Choose an image folder...", command=_pick_folder)
    folder_btn.pack(side="left", padx=8)

    info.pack(fill="x", padx=14, pady=(4, 6))
    opt.pack(fill="x", padx=14, pady=(0, 8))
    convert_btn.config(command=_convert)
    convert_btn.pack(anchor="w", padx=14, pady=(0, 10))
    cancel_btn.config(command=_do_cancel)

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        _probe(sys.argv[1])

    root.mainloop()


def main():
    try:
        _run_gui()
    except Exception:
        tb = traceback.format_exc()
        try:
            LOG_PATH.write_text(tb, encoding="utf-8")
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("Convert for Fiji: could not start",
                                 tb[-1500:] + f"\n\n(log: {LOG_PATH})")
            r.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
