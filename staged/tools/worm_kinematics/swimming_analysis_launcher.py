from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

sys.path.insert(0, str(Path(__file__).resolve().parent))
from swimming_analysis import analyze_csv

root = tk.Tk(); root.withdraw()
path = filedialog.askopenfilename(title="Choose a swimming tracker CSV", filetypes=[("CSV", "*.csv")])
if path:
    threshold = simpledialog.askfloat("Swimming threshold", "Minimum body curvature RMS (degrees) used to call a usable frame swimming:", initialvalue=8.0, minvalue=0.1, parent=root)
    if threshold is not None:
        start = simpledialog.askinteger("Analysis range", "Start frame (Cancel = first frame):", minvalue=0, parent=root)
        end = simpledialog.askinteger("Analysis range", "End frame (Cancel = last frame):", minvalue=0, parent=root)
        try:
            result, out = analyze_csv(path, amplitude_threshold_deg=threshold,start_frame=start,end_frame=end)
            f = result['frequency_hz']
            range_text=f"Frames: {result['selected_frame_start']}–{result['selected_frame_end']}\n"
            messagebox.showinfo("Swimming analysis complete", f"Results: {out}\n\n{range_text}Usable: {result['usable_fraction']:.1%}\nSwimming while usable: {result['swimming_fraction_of_usable']:.1%}\nFrequency: {f:.3f} Hz" if f is not None else f"Results: {out}\n\n{range_text}No defensible frequency was measured.")
        except Exception as exc:
            messagebox.showerror("Swimming analysis", str(exc))
root.destroy()
