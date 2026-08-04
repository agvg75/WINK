from pathlib import Path
import json,sys
import pandas as pd
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog
sys.path.insert(0,str(Path(__file__).resolve().parent))
from orientation_plate_stats import analyse_plates

# Result tables are read through read_table. Under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it - aborting an analysis with an error that names
# numpy internals rather than the column at fault. The import is guarded
# because these modules are launched several different ways and sys.path is
# not identical in all of them; a hard import would turn a latent dtype
# problem into a tool that will not start.
try:
    from table_io import read_table as _read_table
except Exception:                                    # pragma: no cover
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "app"))
        from table_io import read_table as _read_table
    except Exception:
        _read_table = None


def read_table(path, **kwargs):
    """pandas.read_csv with the pandas-3 dtype trap handled where available."""
    import pandas as _pd
    if _read_table is not None:
        return _read_table(path, **kwargs)
    return _pd.read_csv(path, **kwargs)


root=tk.Tk();root.withdraw()
files=filedialog.askopenfilenames(title="Choose plate_resultant.csv files",filetypes=[("Plate result CSV","*.csv")])
if files:
 try:
  rows=[]
  for f in files:
   d=read_table(f)
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
