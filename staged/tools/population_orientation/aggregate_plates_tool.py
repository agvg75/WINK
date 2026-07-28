from pathlib import Path
import json,sys
import pandas as pd
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog
sys.path.insert(0,str(Path(__file__).resolve().parent))
from orientation_plate_stats import analyse_plates

root=tk.Tk();root.withdraw()
files=filedialog.askopenfilenames(title="Choose plate_resultant.csv files",filetypes=[("Plate result CSV","*.csv")])
if files:
 try:
  rows=[]
  for f in files:
   d=pd.read_csv(f)
   if len(d)!=1:raise ValueError(f"Expected exactly one plate row in {f}")
   rows.append(d.iloc[0].to_dict())
  expected=simpledialog.askfloat("Expected direction","Expected stimulus direction in degrees (Cancel for Rayleigh only):",parent=root)
  result=analyse_plates(rows,expected)
  out=Path(filedialog.askdirectory(title="Choose output folder"))
  if str(out) not in {".",""}:
   out.mkdir(parents=True,exist_ok=True);pd.DataFrame(rows).to_csv(out/"included_plate_resultants.csv",index=False)
   pd.DataFrame([result]).to_csv(out/"across_plate_statistics.csv",index=False)
   (out/"across_plate_statistics.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
   messagebox.showinfo("Complete",f"Analyzed {result['n_plates']} independent plates.\nNo pooled-worm test was performed.\nResults: {out}")
 except Exception as e:messagebox.showerror("Across-plate orientation",str(e))
root.destroy()
