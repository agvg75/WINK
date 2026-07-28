from pathlib import Path
import sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"/"morphology"))
from orientation_defaults import load_defaults,save_defaults,image_orientation
with tempfile.TemporaryDirectory(dir=ROOT/"tests") as t:
 p=Path(t)/"defaults.json";d=save_defaults("right_to_left","dorsal_down",p)
 assert load_defaults(p)==d
 assert image_orientation(d)["orientation_source"]=="reused_saved_default"
 assert image_orientation(d,ap="left_to_right")["orientation_source"]=="changed_for_this_image"
print("MORPHOLOGY_ORIENTATION_DEFAULTS_PASS")
