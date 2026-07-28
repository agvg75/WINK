from pathlib import Path
import sys,threading,json
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import cv2
import numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/"movie"));sys.path.insert(0,str(HERE.parents[1]/"app"))
from movie_reader import open_movie
from egg_counter import gray8
from egg_laying import analyze
from process_ui import CockpitApp

class App(CockpitApp):
 def __init__(self):
  super().__init__("Dynamic Egg Laying",geometry="1120x720",process_title="Egg laying")
  self.scale=None;self.roi=None;self.calibration_method=None;self.egg_length_um=50;self.egg_width_um=30;self.reference_egg_points=None;self.reference_eggs=[]
  self.v={k:tk.StringVar(value=v) for k,v in {"source":"","fps":"7.5","known":"1.14","tol":"50","persist":"0.4"}.items()};self.status=tk.StringVar(value="Choose a recording. Calibrate with two points or trace a known-length worm/feature.")
  self._build_controls();self._build_center()
  self.status.trace_add("write",lambda *_:self.set_status(self.status.get()));self.set_status(self.status.get())
 def _build_controls(self):
  c=self.controls
  def field(label,key):
   row=ttk.Frame(c);row.pack(fill="x",pady=2);ttk.Label(row,text=label,width=26,wraplength=185,justify="left").pack(side="left");ttk.Entry(row,textvariable=self.v[key]).pack(side="right",fill="x",expand=True)
  srow=ttk.Frame(c);srow.pack(fill="x",pady=2);ttk.Label(srow,text="Source",width=26).pack(side="left");ttk.Entry(srow,textvariable=self.v["source"]).pack(side="right",fill="x",expand=True)
  pk=ttk.Frame(c);pk.pack(fill="x",pady=(0,4));ttk.Button(pk,text="File",command=self._choose_file).pack(side="left",padx=2);ttk.Button(pk,text="Folder",command=self._choose_folder).pack(side="left",padx=2)
  field("Declared FPS","fps");field("Known length (mm; day-1 = 1.14)","known");field("Egg-size tolerance (%)","tol");field("Minimum persistence (s)","persist")
  ttk.Separator(c,orient="horizontal").pack(fill="x",pady=6)
  ttk.Button(c,text="1a. Two-point calibration + region",command=self.setup_two_point).pack(fill="x",pady=2)
  ttk.Button(c,text="1b. Trace known worm/feature + region",command=self.setup_trace).pack(fill="x",pady=2)
  ttk.Button(c,text="1c. Mark reference egg oval",command=self.mark_reference_egg).pack(fill="x",pady=2)
  self.go=ttk.Button(c,text="2. Analyze and review",command=self.start);self.go.pack(fill="x",pady=(6,2))
 def _choose_file(self):
  p=filedialog.askopenfilename()
  if p:self.v["source"].set(p);self._show_first_frame()
 def _choose_folder(self):
  p=filedialog.askdirectory()
  if p:self.v["source"].set(p);self._show_first_frame()
 def _build_center(self):
  ttk.Label(self.center,text="Dynamic egg laying",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=6,pady=(6,2))
  self.center_fig=Figure(figsize=(5.6,4.0),dpi=100);self.center_ax=self.center_fig.add_subplot(111);self.center_ax.set_axis_off()
  self.center_canvas=FigureCanvasTkAgg(self.center_fig,master=self.center);self.center_canvas.get_tk_widget().pack(fill="both",expand=True,padx=6,pady=(0,4))
  self.center_ax.text(0.5,0.5,"Choose a source; the first frame appears here.",ha="center",va="center",fontsize=10,color="#888888");self.center_canvas.draw()
  ttk.Label(self.center,textvariable=self.status,wraplength=560,justify="left").pack(anchor="w",padx=6,pady=(0,6))
 def _show_first_frame(self):
  try:
   im=self._first_frame()
  except Exception as exc:
   self.status.set(f"Could not load frame: {exc}");return
  self.center_ax.clear();self.center_ax.imshow(im,cmap="gray");self.center_ax.set_axis_off();self.center_ax.set_title("First frame",fontsize=9);self.center_canvas.draw()
 def _first_frame(self):
  m=open_movie(self.v["source"].get());im=gray8(m.get_frame(0));m.close();return im
 def _draw_region(self,im):
  fig,ax=plt.subplots();ax.imshow(im,cmap="gray");ax.set_title("Click around analysis region; press Enter");roi=plt.ginput(-1,timeout=0);plt.close(fig)
  if len(roi)<3:raise ValueError("The analysis region needs at least three points.")
  return roi
 def setup_two_point(self):
  try:
   im=self._first_frame();fig,ax=plt.subplots();ax.imshow(im,cmap="gray");ax.set_title("Two-point calibration: click both ends of a known-length feature");p=plt.ginput(2,timeout=0,show_clicks=True);plt.close(fig)
   if len(p)!=2:raise ValueError("Two-point calibration needs exactly two clicks.")
   pixels=np.hypot(p[1][0]-p[0][0],p[1][1]-p[0][1])
   if pixels<1:raise ValueError("Calibration points are too close together.")
   self.scale=float(self.v["known"].get())*1000/pixels;self.calibration_method="two_point_calibration";self.roi=self._draw_region(im);self.status.set(f"Setup saved by two-point calibration: {pixels:.1f} px = {self.v['known'].get()} mm; {self.scale:.3f} um/pixel")
  except Exception as e:messagebox.showerror("Setup",str(e))
 def setup_trace(self):
  try:
   im=self._first_frame();fig,ax=plt.subplots();ax.imshow(im,cmap="gray");ax.set_title("Trace calibration: click along the known-length worm/feature; press Enter when done");p=plt.ginput(-1,timeout=0,show_clicks=True);plt.close(fig)
   if len(p)<2:raise ValueError("Trace calibration needs at least two points along the worm/feature.")
   pts=np.asarray(p,float);segments=np.diff(pts,axis=0);pixels=float(np.sum(np.hypot(segments[:,0],segments[:,1])))
   if pixels<1:raise ValueError("The traced calibration path is too short.")
   self.scale=float(self.v["known"].get())*1000/pixels;self.calibration_method="segmented_trace_calibration";self.roi=self._draw_region(im);self.status.set(f"Setup saved by traced calibration: {pixels:.1f} px = {self.v['known'].get()} mm; {self.scale:.3f} um/pixel")
  except Exception as e:messagebox.showerror("Setup",str(e))
 def mark_reference_egg(self):
  try:
   if not self.scale:raise ValueError("Calibrate the scale first.")
   im=self._first_frame();examples=self._collect_reference_ovals(im)
   if not examples:raise ValueError("No reference egg was accepted.")
   self.reference_eggs=[];lengths=[];widths=[]
   for ellipse in examples:
    ep=np.asarray(ellipse,np.float32);(_, _),(a,b),angle=cv2.fitEllipse(ep.reshape((-1,1,2)))
    major=max(float(a),float(b))*self.scale;minor=min(float(a),float(b))*self.scale
    self.reference_eggs.append({"points":[tuple(map(float,p)) for p in ellipse],"length_um":major,"width_um":minor,"angle":float(angle)})
    lengths.append(major);widths.append(minor)
   self.reference_egg_points=self.reference_eggs[-1]["points"];self.egg_length_um=float(np.median(lengths));self.egg_width_um=float(np.median(widths))
   self.status.set(f"{len(self.reference_eggs)} accepted reference egg(s) saved for dynamic egg laying. Detector size set to median {self.egg_length_um:.1f} x {self.egg_width_um:.1f} um; rejected examples were ignored.")
  except Exception as e:messagebox.showerror("Reference egg",str(e))
 def _ellipse_from_three_points(self,pts):
  if len(pts)<3:return []
  c=np.asarray(pts[0],float);a=np.asarray(pts[1],float);b=np.asarray(pts[2],float)
  u=a-c;major_r=float(np.hypot(u[0],u[1]))
  if major_r<2:return []
  u=u/major_r;v=np.array([-u[1],u[0]])
  minor_r=abs(float(np.dot(b-c,v)))
  if minor_r<2:minor_r=max(major_r*.55,float(np.hypot(b[0]-c[0],b[1]-c[1]))*.5)
  theta=np.linspace(0,2*np.pi,48,endpoint=False)
  return [tuple((c+major_r*np.cos(t)*u+minor_r*np.sin(t)*v).tolist()) for t in theta]
 def _collect_reference_ovals(self,im):
  fig,ax=plt.subplots();ax.imshow(gray8(im),cmap="gray")
  ax.set_title("Mark reference eggs: click CENTER, LONG-AXIS EDGE, SHORT-AXIS EDGE. Left-click outlined egg = accept. Right-click outlined egg = reject. Close when done.")
  ellipses=[];accepted=[];pending=[];artists=[]
  def nearest(x,y):
   if not ellipses:return None
   centers=[];radii=[]
   for poly in ellipses:
    ep=np.asarray(poly,float);centers.append(ep.mean(axis=0));radii.append(max(8.0,float(np.ptp(ep[:,0]))*.65,float(np.ptp(ep[:,1]))*.65))
   centers=np.asarray(centers,float);d=np.hypot(centers[:,0]-x,centers[:,1]-y);j=int(np.argmin(d))
   return j if d[j]<=radii[j] else None
  def redraw():
   nonlocal artists
   for a in artists:
    try:a.remove()
    except Exception:pass
   artists=[]
   for i,poly in enumerate(ellipses):
    ep=np.asarray(poly,float);color="lime" if accepted[i] else "red"
    line,=ax.plot(np.r_[ep[:,0],ep[0,0]],np.r_[ep[:,1],ep[0,1]],color=color,lw=2);artists.append(line)
    try:
     (_, _),(aa,bb),ang=cv2.fitEllipse(ep.reshape((-1,1,2)).astype(np.float32));maj=max(float(aa),float(bb));theta=np.deg2rad(float(ang)+(90.0 if aa<bb else 0.0));cx,cy=ep.mean(axis=0);dx=np.cos(theta)*maj*.5;dy=np.sin(theta)*maj*.5
     axis,=ax.plot([cx-dx,cx+dx],[cy-dy,cy+dy],"c-" if accepted[i] else "m-",lw=1);artists.append(axis)
    except Exception:pass
    artists.append(ax.text(float(ep[:,0].mean()),float(ep[:,1].mean()),str(i+1),color=color,fontsize=9,weight="bold"))
   if pending:
    artists.append(ax.scatter([p[0] for p in pending],[p[1] for p in pending],c="cyan",s=24))
   fig.canvas.draw_idle()
  def click(e):
   if e.inaxes!=ax or e.xdata is None or e.ydata is None:return
   j=nearest(float(e.xdata),float(e.ydata))
   if e.button==3:
    if j is not None:accepted[j]=False;redraw()
    return
   if e.button!=1:return
   if j is not None:
    accepted[j]=True;redraw();return
   pending.append((float(e.xdata),float(e.ydata)))
   if len(pending)==3:
    poly=self._ellipse_from_three_points(pending);pending.clear()
    if poly:ellipses.append(poly);accepted.append(True)
   redraw()
  fig.canvas.mpl_connect("button_press_event",click);redraw();plt.show()
  return [p for p,a in zip(ellipses,accepted) if a]
 def start(self):
  try:
   if not self.scale or len(self.roi)<3:raise ValueError("Complete setup first.")
   args=(self.v["source"].get(),float(self.v["fps"].get()),self.scale,self.roi,None,float(self.v["tol"].get())/100,float(self.v["persist"].get()),25,self.calibration_method or "two_point_calibration",self.egg_length_um,self.egg_width_um)
  except Exception as e:messagebox.showerror("Inputs",str(e));return
  self.go.state(["disabled"]);threading.Thread(target=self.run,args=(args,),daemon=True).start()
 def run(self,args):
  try:
   source,fps,scale,roi,out,tol,persist,max_match,calibration_method,egg_len,egg_wid=args
   e,o=analyze(source,fps,scale,roi,out,tol,persist,max_match,calibration_method,
               progress=lambda i,n:self.after(0,self.status.set,f"Analyzing frame {i} of {n}..."),
               egg_length_um=egg_len,egg_width_um=egg_wid)
   self.after(0,self.review,e,o)
  except Exception as x:self.after(0,self.fail,str(x))
 def review(self,e,out):
  self.go.state(["!disabled"]);accepted=[True]*len(e);times=e.event_time_s.tolist() if len(e) else []
  fig,ax=plt.subplots();ax.set_title("Event candidates: click to accept/reject; Shift+click to add; close to save");ax.set_xlabel("Time (s)");ax.set_yticks([]);sc=ax.scatter(times,[1]*len(times),c="green")
  def redraw():sc.set_offsets(np.c_[times,[1]*len(times)] if times else np.empty((0,2)));sc.set_color(["green" if a else "red" for a in accepted]);fig.canvas.draw_idle()
  def click(x):
   if x.inaxes!=ax or x.xdata is None:return
   if x.key=="shift":times.append(x.xdata);accepted.append(True)
   elif times:
    j=int(np.argmin(np.abs(np.asarray(times)-x.xdata)));accepted[j]=not accepted[j]
   redraw()
  fig.canvas.mpl_connect("button_press_event",click);plt.show();r=pd.DataFrame({"event_time_s":times,"accepted":accepted,"source":["automatic" if i<len(e) else "manual_add" for i in range(len(times))]});r.to_csv(out/"reviewed_egg_laying_events.csv",index=False)
  summary={"reviewed_event_count":int(r.accepted.sum()),"reviewed_event_times_s":r.loc[r.accepted,"event_time_s"].tolist(),"review_required":True};(out/"reviewed_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");self.status.set(f"Reviewed {summary['reviewed_event_count']} events. Results: {out}");messagebox.showinfo("Complete",self.status.get())
 def fail(self,e):self.go.state(["!disabled"]);self.status.set("Stopped");messagebox.showerror("Egg laying",e)
if __name__=="__main__":App().mainloop()
