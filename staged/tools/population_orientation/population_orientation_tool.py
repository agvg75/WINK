import sys,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import matplotlib.pyplot as plt
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"movie"));sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
from movie_reader import open_movie
from population_orientation import analyze,gray8
from acquisition import AcquisitionMetadata
from run_feedback import prompt_post_run_feedback

class App(tk.Tk):
 def __init__(self):
  super().__init__();self.title("Population Orientation - Plate State");self.geometry("760x480")
  self.v={k:tk.StringVar(value=v) for k,v in {"source":"","plate":"","fps":"1","known":"20","radius":"2","worms":""}.items()};self.points=None;self.scale=None;self.status=tk.StringVar(value="Choose a movie, TIFF stack, or image folder.")
  labels=[("Source","source"),("Plate ID (required)","plate"),("Declared FPS","fps"),("Calibration distance (mm)","known"),("ROI radius (mm)","radius"),("Approximate worms on plate","worms")]
  for i,(lab,key) in enumerate(labels):ttk.Label(self,text=lab).grid(row=i,column=0,padx=10,pady=6,sticky="w");ttk.Entry(self,textvariable=self.v[key],width=60).grid(row=i,column=1,pady=6)
  ttk.Button(self,text="Choose file",command=self.file).grid(row=0,column=2);ttk.Button(self,text="Choose folder",command=self.folder).grid(row=1,column=2)
  ttk.Button(self,text="1. Calibrate and mark positions",command=self.mark).grid(row=7,column=0,columnspan=2,pady=12)
  self.go=ttk.Button(self,text="2. Analyze plate",command=self.start);self.go.grid(row=8,column=0,columnspan=2,pady=8)
  ttk.Label(self,textvariable=self.status,wraplength=720).grid(row=9,column=0,columnspan=3,padx=10,pady=10,sticky="w")
 def file(self):self.v["source"].set(filedialog.askopenfilename())
 def folder(self):self.v["source"].set(filedialog.askdirectory())
 def mark(self):
  try:
   m=open_movie(self.v["source"].get());im,_=gray8(m.get_frame(0));m.close();known=float(self.v["known"].get())
   fig,ax=plt.subplots();ax.imshow(im,cmap="gray");ax.set_title("Click: calibration start, calibration end, stimulus, control, release");p=plt.ginput(5,timeout=0);plt.close(fig)
   if len(p)!=5:return
   px=((p[1][0]-p[0][0])**2+(p[1][1]-p[0][1])**2)**.5;self.scale=known*1000/px;self.points=p[2:];self.status.set(f"Scale {self.scale:.3f} um/pixel. Stimulus, control, and release positions saved.")
  except Exception as e:messagebox.showerror("Setup",str(e))
 def start(self):
  try:
   if not self.points or not self.scale:raise ValueError("Complete calibration and position marking first.")
   plate=self.v["plate"].get().strip()
   if not plate:raise ValueError("Plate ID is required.")
   worms=int(self.v["worms"].get()) if self.v["worms"].get().strip() else None
   args=(self.v["source"].get(),plate,float(self.v["fps"].get()),self.scale,*self.points,float(self.v["radius"].get())*1000/self.scale,None,1,2,150,.8,worms)
  except Exception as e:messagebox.showerror("Inputs",str(e));return
  self.go.state(["disabled"]);threading.Thread(target=self.run,args=(args,),daemon=True).start()
 def run(self,args):
  try:r,o=analyze(*args,progress=lambda i,n:self.after(0,self.status.set,f"Analyzing frame {i} of {n}..."));self.after(0,self.done,r,o)
  except Exception as e:self.after(0,self.fail,str(e))
 def done(self,r,o):
  self.go.state(["!disabled"]);self.status.set(f"Complete. Results: {o}");messagebox.showinfo("Complete",f"Plate {r['plate_id']} complete.\nResults: {o}")
  acquisition=AcquisitionMetadata(float(self.v["fps"].get()),"declared",float(self.scale),"two_point_calibration",None,"not_applicable",compression="unknown",channel_identity="brightfield",anatomical_orientation="unknown")
  prompt_post_run_feedback(tool_name="Population orientation (Plate state)",tool_version="0.1.0",run_id=str(r["plate_id"]),acquisition=acquisition,parameters={"roi_radius_mm":float(self.v["radius"].get()),"approximate_worms":self.v["worms"].get()},parent=self,evidence_paths=[Path(o)/"analysis_metadata.json"] if (Path(o)/"analysis_metadata.json").exists() else None)
 def fail(self,e):self.go.state(["!disabled"]);self.status.set("Stopped");messagebox.showerror("Orientation",e)
if __name__=="__main__":App().mainloop()
