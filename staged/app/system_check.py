"""Runtime check used by the student installer."""
import argparse,importlib,os,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
MODULES=["numpy","pandas","scipy","matplotlib","PIL","tifffile","imageio","cv2","skimage","tkinterdnd2"]
def main(quiet=False):
 failed=[]
 for name in MODULES:
  try:importlib.import_module(name)
  except Exception as e:failed.append(f"module {name}: {e}")
 try:p=Path(tempfile.gettempdir())/"agvg_write_test.tmp";p.write_text("ok");p.unlink()
 except Exception as e:failed.append(f"temporary-folder write: {e}")
 fiji_candidates = [
  Path(os.path.expandvars(r"%LOCALAPPDATA%\Fiji.app\ImageJ-win64.exe")),
  Path(os.path.expandvars(r"%LOCALAPPDATA%\AGVGLab\runtime_layer\Fiji.app\ImageJ-win64.exe")),
  Path(os.path.expandvars(r"%LOCALAPPDATA%\AGVGLab\runtime_layer\Fiji.app\fiji-windows-x64.exe"))]
 if not any(path.exists() for path in fiji_candidates):failed.append("Fiji not found")
 if not(ROOT/"app"/"lab_hub.py").exists():failed.append("Lab Hub files missing")
 if failed:
  print("LAB TOOLS SYSTEM CHECK FAILED");[print("-",x) for x in failed];return 1
 if not quiet:print("LAB TOOLS SYSTEM CHECK PASSED")
 return 0
if __name__=="__main__":
 a=argparse.ArgumentParser();a.add_argument("--quiet",action="store_true");o=a.parse_args();raise SystemExit(main(o.quiet))
