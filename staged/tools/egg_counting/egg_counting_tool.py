from pathlib import Path
import sys,json,base64,io,uuid,datetime
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import cv2,numpy as np,pandas as pd
from PIL import Image,ImageDraw
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/"movie"))
sys.path.insert(0,str(HERE.parents[1]/"app"))
from movie_reader import open_movie
from acquisition import AcquisitionMetadata
from egg_counter import detect_eggs,gray8,_odd,_intensity_context
from segmentation_review import find_accepted_config,segment_frame
from decision_transparency import write_decision_manifest,vote_policy_summary
from process_ui import ProcessLog,ReviewWorkbench,collect_image_points,standardize_matplotlib_window,apply_wink_theme,CockpitApp

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


class App(CockpitApp):
 def __init__(self):
  super().__init__("Endpoint Egg Counting",geometry="1260x820",process_title="Egg counting")
  self.source=tk.StringVar();self.frame=tk.StringVar(value="0");self.known=tk.StringVar(value="1.0");self.worm_length=tk.StringVar(value="1.14");self.tol=tk.StringVar(value="25");self.status=tk.StringVar(value="Choose an image, TIFF stack, movie, or image folder.");self.scale=None;self.roi=None;self.image=None;self.calibration_method=None;self.calibration_points=None;self.calibration_length_px=None;self.egg_length_um=None;self.egg_width_um=None;self.reference_egg_points=None;self.reference_eggs=[]
  self.use_library=tk.BooleanVar(value=True);self.learn_library=tk.BooleanVar(value=True)
  self.dials={k:tk.StringVar(value=v) for k,v in {
   "major_min":"","major_max":"","minor_min":"","minor_max":"",
   "aspect_min":"1.15","aspect_max":"2.60","solidity":"0.82",
   "fill_min":"0.55","fill_max":"1.18","rim":"0.045",
   "bright_min":"","bright_max":"","local_contrast":"","bright_contrast":"",
   "dark_contrast":"","intensity_span":"","template_match":"","false_positive_match":"0.72","max_library_prototypes":"8",
   "min_votes":"5","min_contrast_votes":"2"}.items()}
  self._review_ctx=None;self._refresh_after=None
  for v in self.dials.values():v.trace_add("write",lambda *args:self._schedule_review_refresh())
  self._build_controls();self._build_center()
  self.status.trace_add("write",lambda *_:self.set_status(self.status.get()));self.set_status(self.status.get())
 def _build_controls(self):
  c=self.controls
  def field(label,var):
   row=ttk.Frame(c);row.pack(fill="x",pady=2);ttk.Label(row,text=label,width=24,wraplength=170,justify="left").pack(side="left");ttk.Entry(row,textvariable=var).pack(side="right",fill="x",expand=True)
  srow=ttk.Frame(c);srow.pack(fill="x",pady=2);ttk.Label(srow,text="Source",width=24).pack(side="left");ttk.Entry(srow,textvariable=self.source).pack(side="right",fill="x",expand=True)
  pk=ttk.Frame(c);pk.pack(fill="x",pady=(0,4));ttk.Button(pk,text="Choose file",command=self._choose_file).pack(side="left",padx=2);ttk.Button(pk,text="Choose folder",command=self._choose_folder).pack(side="left",padx=2)
  field("Frame number",self.frame);field("Calibration distance (mm)",self.known);field("Size tolerance (%)",self.tol);field("Day-1 worm length (mm)",self.worm_length)
  ttk.Separator(c,orient="horizontal").pack(fill="x",pady=6)
  ttk.Button(c,text="1a. Calibrate straight distance",command=self.calibrate).pack(fill="x",pady=2)
  ttk.Button(c,text="1b. Calibrate from worm trace",command=self.calibrate_worm_trace).pack(fill="x",pady=2)
  ttk.Button(c,text="2. Draw analysis region",command=self.draw_roi).pack(fill="x",pady=2)
  ttk.Button(c,text="3. Mark reference egg(s)",command=self.mark_reference_egg).pack(fill="x",pady=2)
  ttk.Button(c,text="4. Detect and review eggs",command=self.review).pack(fill="x",pady=2)
  ttk.Button(c,text="Refresh open review from dials",command=self.refresh_open_review).pack(fill="x",pady=2)
  ttk.Checkbutton(c,text="Use lab egg library for suggestions",variable=self.use_library,command=self._schedule_review_refresh).pack(anchor="w",pady=(4,0))
  ttk.Checkbutton(c,text="Contribute reviewed eggs to lab library",variable=self.learn_library).pack(anchor="w")
 def _choose_file(self):
  p=filedialog.askopenfilename()
  if p:self.source.set(p);self._show_first_frame()
 def _choose_folder(self):
  p=filedialog.askdirectory()
  if p:self.source.set(p);self._show_first_frame()
 def _build_center(self):
  ttk.Label(self.center,text="Endpoint egg counting",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=6,pady=(6,2))
  self.center_fig=Figure(figsize=(5.4,3.6),dpi=100);self.center_ax=self.center_fig.add_subplot(111);self.center_ax.set_axis_off()
  self.center_canvas=FigureCanvasTkAgg(self.center_fig,master=self.center);self.center_canvas.get_tk_widget().pack(fill="both",expand=True,padx=6,pady=(0,4))
  self.center_ax.text(0.5,0.5,"Choose a source; the frame appears here.",ha="center",va="center",fontsize=10,color="#888888");self.center_canvas.draw()
  ttk.Label(self.center,textvariable=self.status,wraplength=560,justify="left").pack(anchor="w",padx=6,pady=(0,4))
  box=ttk.LabelFrame(self.center,text="Advanced egg-detection dials (blank = default/from reference egg)");box.pack(fill="x",padx=6,pady=(2,6))
  labs=[("Major axis min/max um","major_min","major_max"),("Minor axis min/max um","minor_min","minor_max"),("Aspect min/max","aspect_min","aspect_max"),("Ellipse fill min/max","fill_min","fill_max"),("Brightness min/max 0-255","bright_min","bright_max")]
  for r,(lab,a,b) in enumerate(labs):
   ttk.Label(box,text=lab).grid(row=r,column=0,padx=8,pady=3,sticky="w");ttk.Entry(box,textvariable=self.dials[a],width=9).grid(row=r,column=1,padx=4,pady=3);ttk.Entry(box,textvariable=self.dials[b],width=9).grid(row=r,column=2,padx=4,pady=3)
  extra=[("Solidity min","solidity"),("Rim contrast min","rim"),("Egg-bg contrast min","local_contrast"),("Bright side min","bright_contrast"),("Dark side min","dark_contrast"),("Brightness span min","intensity_span"),("Template match min","template_match"),("Reject-memory match","false_positive_match"),("Max library prototypes","max_library_prototypes"),("Min egg votes","min_votes"),("Min contrast votes","min_contrast_votes")]
  for r,(lab,k) in enumerate(extra):
   ttk.Label(box,text=lab).grid(row=r,column=3,padx=12,pady=3,sticky="w");ttk.Entry(box,textvariable=self.dials[k],width=9).grid(row=r,column=4,padx=4,pady=3)
  ttk.Button(box,text="Reset dials",command=self.reset_dials).grid(row=5,column=1,columnspan=2,padx=8,pady=4,sticky="w")
 def _show_first_frame(self):
  try:
   im=self.load()
  except Exception as exc:
   self.status.set(f"Could not load frame: {exc}");return
  self.center_ax.clear();self.center_ax.imshow(im,cmap="gray");self.center_ax.set_axis_off();self.center_ax.set_title(f"Frame {self.frame.get()}",fontsize=9);self.center_canvas.draw()
 def reset_dials(self):
  defaults={"major_min":"","major_max":"","minor_min":"","minor_max":"","aspect_min":"1.15","aspect_max":"2.60","solidity":"0.82","fill_min":"0.55","fill_max":"1.18","rim":"0.045","bright_min":"","bright_max":"","local_contrast":"","bright_contrast":"","dark_contrast":"","intensity_span":"","template_match":"","false_positive_match":"0.72","max_library_prototypes":"8","min_votes":"5","min_contrast_votes":"2"}
  for k,v in defaults.items():self.dials[k].set(v)
  self.status.set("Egg-detection dials reset. Reference egg size is preserved if one was marked.")
 def dial_float(self,k,default=None):
  s=self.dials[k].get().strip()
  return default if s=="" else float(s)
 def _schedule_review_refresh(self):
  if self._review_ctx is None:return
  if self._refresh_after is not None:
   try:self.after_cancel(self._refresh_after)
   except Exception:pass
  self._refresh_after=self.after(450,self.refresh_open_review)
 def load(self):
  m=open_movie(self.source.get());i=int(self.frame.get());self.image=m.get_frame(i);m.close();return gray8(self.image)
 def calibrate(self):
  try:
   im=self.load();p=collect_image_points(self,im,title="Calibrate straight distance",instructions="Click the two ends of a feature with the declared length.",mode="polyline",min_points=2,max_points=2,process_log=ProcessLog("Egg counting calibration"))
   if p is None:return
   if len(p)==2:
    self.calibration_points=[tuple(map(float,q)) for q in p];self.calibration_length_px=float(np.hypot(p[1][0]-p[0][0],p[1][1]-p[0][1]));self.calibration_method="two_point_calibration";self.scale=float(self.known.get())*1000/self.calibration_length_px;self.status.set(f"Scale saved: {self.scale:.3f} um/pixel")
  except Exception as e:messagebox.showerror("Calibration",str(e))
 def calibrate_worm_trace(self):
  try:
   im=self.load();p=collect_image_points(self,im,title="Calibrate from worm trace",instructions="Click along the worm from one end to the other; use Undo/Clear if needed, then Finish.",mode="polyline",min_points=2,process_log=ProcessLog("Egg counting worm-trace calibration"))
   if p is None:return
   if len(p)<2:return
   pts=np.asarray(p,float);seg=np.diff(pts,axis=0);path_px=float(np.sum(np.hypot(seg[:,0],seg[:,1])))
   if path_px<=0:raise ValueError("The traced worm path has zero length.")
   self.calibration_points=[tuple(map(float,q)) for q in p];self.calibration_length_px=path_px;self.calibration_method="segmented_worm_trace";self.scale=float(self.worm_length.get())*1000/path_px;self.status.set(f"Scale saved from worm trace: {self.scale:.3f} um/pixel ({float(self.worm_length.get()):.2f} mm / {path_px:.1f} px)")
  except Exception as e:messagebox.showerror("Worm trace calibration",str(e))
 def draw_roi(self):
  try:
   im=self.load();p=collect_image_points(self,im,title="Draw egg analysis region",instructions="Click around the analysis region. The polygon closes automatically when you Finish.",mode="polygon",min_points=3,process_log=ProcessLog("Egg counting analysis-region ROI"))
   if p is None:return
   if len(p)>=3:self.roi=p;self.status.set(f"Analysis region saved ({len(p)} boundary points).")
  except Exception as e:messagebox.showerror("Region",str(e))
 def mark_reference_egg(self):
  try:
   if not self.scale:raise ValueError("Calibrate the scale first.")
   im=self.load();self.reference_eggs=[];self.reference_egg_points=None
   examples=self._collect_reference_ovals(im)
   if not examples:raise ValueError("No reference egg was accepted.")
   for p in examples:
    egg=self._measure_reference_points(p,im)
    self.reference_eggs.append(egg);self.reference_egg_points=egg["points"]
   self._prepopulate_dials_from_references()
   self.status.set(f"{len(self.reference_eggs)} accepted reference egg(s) saved. Rejected examples were ignored. Dials were pre-populated from the accepted egg sizes and contrast prototypes; template patches include surrounding rim/background pixels.")
  except Exception as e:messagebox.showerror("Reference egg",str(e))
 def _ellipse_from_three_points(self,pts):
  if len(pts)<3:return []
  c=np.asarray(pts[0],float);a=np.asarray(pts[1],float);b=np.asarray(pts[2],float)
  u=a-c;major_r=float(np.hypot(u[0],u[1]))
  if major_r<2:return []
  u=u/major_r
  v=np.array([-u[1],u[0]])
  minor_r=abs(float(np.dot(b-c,v)))
  if minor_r<2:
   # If the third click is imperfect, use its perpendicular distance to the
   # long axis first and fall back to a plausible C. elegans egg width.
   minor_r=max(major_r*.55,float(np.hypot(b[0]-c[0],b[1]-c[1]))*.5)
  theta=np.linspace(0,2*np.pi,48,endpoint=False)
  return [tuple((c+major_r*np.cos(t)*u+minor_r*np.sin(t)*v).tolist()) for t in theta]
 def _collect_reference_ovals(self,im):
  proc=ProcessLog("Egg reference examples")
  proc.add("Reference egg marking","Mark multiple example eggs without closing and reopening the tool.","ready")
  wb=ReviewWorkbench(self,"Mark reference egg examples",proc,width=1380,height=880)
  wb.set_status("Click center, long-axis edge, short-axis edge. Then left-click an outlined egg to accept or right-click to reject.")
  fig,ax=wb.fig,wb.ax
  ax.imshow(gray8(im),cmap="gray")
  ax.set_title("Mark reference eggs: click CENTER, LONG-AXIS EDGE, SHORT-AXIS EDGE. Left-click outlined egg = accept. Right-click outlined egg = reject. Close when done.")
  ellipses=[];accepted=[];pending=[];artists=[]
  cancelled={"value":False}
  def finish():
   wb.close()
  def cancel():
   cancelled["value"]=True;wb.close()
  def undo():
   if pending:
    pending.pop();proc.add("Undo reference point",f"{len(pending)} point(s) remain in current egg.","edit")
   elif ellipses:
    ellipses.pop();accepted.pop();proc.add("Undo reference egg",f"{len(ellipses)} egg example(s) remain.","edit")
   redraw();wb.refresh_hood()
  def clear():
   pending.clear();ellipses.clear();accepted.clear();proc.add("Clear reference eggs","All reference examples cleared.","edit");redraw();wb.refresh_hood()
  wb.clear_controls()
  wb.add_control_label("Reference egg examples")
  wb.add_control_label("For each egg: click center, then one end of the long axis, then one side of the short axis. Surrounding pixels are kept for contrast/template learning.")
  wb.add_control_button("Finish / accept examples",finish)
  wb.add_control_button("Undo last point/egg",undo)
  wb.add_control_button("Clear and restart",clear)
  wb.add_control_button("Cancel",cancel)
  wb.add_control_separator()
  wb.add_control_button("Hide controls (c)",wb.toggle_controls)
  wb.add_control_button("Hide hood (h)",wb.toggle_hood)
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
    line,=ax.plot(np.r_[ep[:,0],ep[0,0]],np.r_[ep[:,1],ep[0,1]],color=color,lw=2)
    artists.append(line)
    try:
     (_, _),(aa,bb),ang=cv2.fitEllipse(ep.reshape((-1,1,2)).astype(np.float32));maj=max(float(aa),float(bb));theta=np.deg2rad(float(ang)+(90.0 if aa<bb else 0.0));cx,cy=ep.mean(axis=0);dx=np.cos(theta)*maj*.5;dy=np.sin(theta)*maj*.5
     axis,=ax.plot([cx-dx,cx+dx],[cy-dy,cy+dy],"c-" if accepted[i] else "m-",lw=1)
     artists.append(axis)
    except Exception:pass
    txt=ax.text(float(ep[:,0].mean()),float(ep[:,1].mean()),str(i+1),color=color,fontsize=9,weight="bold")
    artists.append(txt)
   if pending:
    px=[p[0] for p in pending];py=[p[1] for p in pending];sc=ax.scatter(px,py,c="cyan",s=24);artists.append(sc)
   wb.refresh()
  def click(e):
   if e.inaxes!=ax or e.xdata is None or e.ydata is None:return
   j=nearest(float(e.xdata),float(e.ydata))
   if e.button==3:
    if j is not None:
     accepted[j]=False;proc.add("Rejected reference-like object",f"example {j+1} marked red.","review");redraw();wb.refresh_hood()
    return
   if e.button!=1:return
   if j is not None:
    accepted[j]=True;proc.add("Accepted reference egg",f"example {j+1} marked green.","review");redraw();wb.refresh_hood();return
   pending.append((float(e.xdata),float(e.ydata)))
   proc.add("Reference point added",f"{len(pending)}/3 points for current egg.","edit")
   if len(pending)==3:
    poly=self._ellipse_from_three_points(pending);pending.clear()
    if poly:
     ellipses.append(poly);accepted.append(True);proc.add("Reference egg proposed","Outlined egg is green/accepted; right-click it if it is not a good example.","review")
   redraw();wb.refresh_hood()
  def key(e):
   key=str(getattr(e,"key","") or "").lower()
   if key in ("enter","return"):finish()
   elif key in ("backspace","delete"):undo()
   elif key=="escape":cancel()
  fig.canvas.mpl_connect("button_press_event",click);fig.canvas.mpl_connect("key_press_event",key);redraw();wb.wait()
  if cancelled["value"]:return []
  return [p for p,a in zip(ellipses,accepted) if a]
 def _measure_reference_points(self,p,im=None):
   pts=np.asarray(p,np.float32)
   if len(pts)>=5:
    c=pts.reshape((-1,1,2)).astype(np.float32)
    (_, _),(a,b),angle=cv2.fitEllipse(c)
    major=max(float(a),float(b));minor=min(float(a),float(b))
   else:
    x0,y0=pts.min(axis=0);x1,y1=pts.max(axis=0);major=max(float(x1-x0),float(y1-y0));minor=min(float(x1-x0),float(y1-y0));angle=0.0
   if major<2 or minor<2:raise ValueError("Reference egg is too small. Please mark a clear egg tightly.")
   mean_intensity=np.nan
   local_background=np.nan;local_contrast=np.nan;bright_contrast=np.nan;dark_contrast=np.nan;intensity_span=np.nan
   if im is not None:
    g=gray8(im);mask=np.zeros(g.shape,np.uint8)
    if len(pts)>=3:
     cv2.fillPoly(mask,[pts.astype(np.int32)],255)
    else:
     x0,y0=pts.min(axis=0);x1,y1=pts.max(axis=0);cv2.rectangle(mask,(int(x0),int(y0)),(int(x1),int(y1)),255,-1)
    if np.any(mask>0):
     vals=g[mask>0].astype(np.float32);mean_intensity=float(np.mean(vals))
     k=max(5,int(round(minor*.6)));outer=cv2.dilate(mask,np.ones((_odd(k,3),_odd(k,3)),np.uint8));bg=(outer>0)&(mask==0)
     local_background=float(np.mean(g[bg].astype(np.float32))) if np.any(bg) else mean_intensity
     p10=float(np.percentile(vals,10));p90=float(np.percentile(vals,90))
     local_contrast=abs(mean_intensity-local_background)/255.0
     bright_contrast=max(0.0,(p90-local_background)/255.0)
     dark_contrast=max(0.0,(local_background-p10)/255.0)
     intensity_span=max(0.0,(p90-p10)/255.0)
   return dict(points=[tuple(map(float,q)) for q in p],length_px=major,width_px=minor,
               length_um=major*self.scale,width_um=minor*self.scale,
               aspect_ratio=major/max(minor,1e-6),angle_deg=float(angle),
               mean_intensity=mean_intensity,local_background=local_background,
               local_contrast=local_contrast,bright_contrast=bright_contrast,
               dark_contrast=dark_contrast,intensity_span=intensity_span)
 def _prepopulate_dials_from_references(self):
   refs=self.reference_eggs or ([self._measure_reference_points(self.reference_egg_points)] if self.reference_egg_points else [])
   if not refs:return
   lengths=[r["length_um"] for r in refs];widths=[r["width_um"] for r in refs];aspects=[r["aspect_ratio"] for r in refs]
   self.egg_length_um=float(np.median(lengths));self.egg_width_um=float(np.median(widths))
   tol=float(self.tol.get())/100
   self.dials["major_min"].set(f"{min(lengths)*(1-tol):.1f}");self.dials["major_max"].set(f"{max(lengths)*(1+tol):.1f}")
   self.dials["minor_min"].set(f"{min(widths)*(1-tol):.1f}");self.dials["minor_max"].set(f"{max(widths)*(1+tol):.1f}")
   self.dials["aspect_min"].set(f"{max(1.05,min(aspects)*.85):.2f}");self.dials["aspect_max"].set(f"{max(aspects)*1.20:.2f}")
   intensities=[float(r["mean_intensity"]) for r in refs if not np.isnan(float(r.get("mean_intensity",np.nan)))]
   if intensities:
    pad=max(18.0,(max(intensities)-min(intensities))*.75)
    self.dials["bright_min"].set(f"{max(0.0,min(intensities)-pad):.0f}")
    self.dials["bright_max"].set(f"{min(255.0,max(intensities)+pad):.0f}")
   for key,dial,pad_frac in [("local_contrast","local_contrast",.50),("bright_contrast","bright_contrast",.60),("dark_contrast","dark_contrast",.60),("intensity_span","intensity_span",.50)]:
    vals=[float(r[key]) for r in refs if not np.isnan(float(r.get(key,np.nan)))]
    if vals:self.dials[dial].set(f"{max(0.0,min(vals)*(1-pad_frac)):.3f}")
   if refs and not self.dials["template_match"].get().strip():self.dials["template_match"].set("0.42")
 def _reference_candidate(self):
  refs=self.reference_eggs or ([dict(points=self.reference_egg_points)] if self.reference_egg_points else [])
  if not refs or not self.scale:return []
  out=[]
  for ref0 in refs:
   pts=np.asarray(ref0["points"],np.float32)
   if len(pts)<2:continue
   x=float(np.mean(pts[:,0]));y=float(np.mean(pts[:,1]))
   if len(pts)>=5:
    c=pts.reshape((-1,1,2)).astype(np.float32);(_, _),(a,b),angle=cv2.fitEllipse(c)
    major=max(float(a),float(b));minor=min(float(a),float(b))
   else:
    x0,y0=pts.min(axis=0);x1,y1=pts.max(axis=0);major=max(float(x1-x0),float(y1-y0));minor=min(float(x1-x0),float(y1-y0));angle=0.0
   if major<2 or minor<2:continue
   out.append(dict(x=x,y=y,length_um=major*self.scale,width_um=minor*self.scale,
               angle_deg=float(angle),score=-999.0,aspect_ratio=major/max(minor,1e-6),
               solidity=1.0,ellipse_fill=1.0,rim_gradient=np.nan,edge_polarity=np.nan,mean_intensity=np.nan,
               local_background=np.nan,local_contrast=np.nan,bright_contrast=np.nan,dark_contrast=np.nan,intensity_span=np.nan,
               source="reference_seed"))
  return out
 def _old_reference_candidate(self):
  if not self.reference_egg_points or not self.scale:return None
  pts=np.asarray(self.reference_egg_points,np.float32)
  x=float(np.mean(pts[:,0]));y=float(np.mean(pts[:,1]))
  if len(pts)>=5:
   c=pts.reshape((-1,1,2)).astype(np.float32);(_, _),(a,b),angle=cv2.fitEllipse(c)
   major=max(float(a),float(b));minor=min(float(a),float(b))
  else:
   x0,y0=pts.min(axis=0);x1,y1=pts.max(axis=0);major=max(float(x1-x0),float(y1-y0));minor=min(float(x1-x0),float(y1-y0));angle=0.0
  if major<2 or minor<2:return None
  return dict(x=x,y=y,length_um=major*self.scale,width_um=minor*self.scale,
              angle_deg=float(angle),score=-999.0,aspect_ratio=major/max(minor,1e-6),
              solidity=1.0,ellipse_fill=1.0,rim_gradient=np.nan,edge_polarity=np.nan,mean_intensity=np.nan,
              local_background=np.nan,local_contrast=np.nan,bright_contrast=np.nan,dark_contrast=np.nan,intensity_span=np.nan,
              source="reference_seed")
 def _feature_image(self,im):
  g=gray8(im)
  clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(g)
  bg=cv2.GaussianBlur(clahe,(_odd(41,15),_odd(41,15)),0)
  feat=cv2.addWeighted(clahe,1.0,bg,-1.0,128)
  return cv2.GaussianBlur(feat,(3,3),0)
 def _library_path(self):
  # Keep the learned egg library outside versioned Current_Files folders.
  # Otherwise each WINK update starts with an empty "brain", and student
  # approvals/rejections from v11.53 do not help v11.55.
  for parent in HERE.parents:
   if parent.name.lower()=="lab tools":
    return parent/"shared_state"/"egg_counting"/"egg_prototype_library.json"
  return HERE/"egg_prototype_library.json"
 def _load_library(self):
  path=self._library_path()
  if not path.exists():return {"version":1,"prototypes":[],"false_positive_traps":[]}
  try:
   data=json.loads(path.read_text(encoding="utf-8"))
   if not isinstance(data,dict):raise ValueError("bad library")
   data.setdefault("version",1);data.setdefault("prototypes",[]);data.setdefault("false_positive_traps",[])
   return data
  except Exception:
   return {"version":1,"prototypes":[],"false_positive_traps":[],"load_warning":"Could not read existing library; ignored for safety."}
 def _save_library(self,data):
  data["updated_at"]=datetime.datetime.now().isoformat(timespec="seconds")
  path=self._library_path();path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps(data,indent=2),encoding="utf-8")
 def _encode_patch(self,patch):
  patch=np.asarray(patch,np.uint8)
  bio=io.BytesIO();Image.fromarray(patch).save(bio,format="PNG")
  return base64.b64encode(bio.getvalue()).decode("ascii")
 def _decode_patch(self,text):
  try:
   return np.array(Image.open(io.BytesIO(base64.b64decode(text))).convert("L"))
  except Exception:
   return None
 def _source_context(self,im):
  g=gray8(im)
  return dict(source_name=Path(self.source.get()).name,frame=int(self.frame.get()),
              mean=float(np.mean(g)),std=float(np.std(g)),p10=float(np.percentile(g,10)),
              p90=float(np.percentile(g,90)),um_per_px=float(self.scale or np.nan))
 def _reference_templates(self,im):
  feat=self._feature_image(im);h,w=feat.shape;templates=[]
  for ri,ref in enumerate(self.reference_eggs):
   pts=np.asarray(ref["points"],np.float32)
   if len(pts)<2:continue
   x0,y0=pts.min(axis=0);x1,y1=pts.max(axis=0)
   pad=max(6,int(round(max(ref.get("length_px",x1-x0),ref.get("width_px",y1-y0))*.65)))
   x0=max(0,int(np.floor(x0-pad)));y0=max(0,int(np.floor(y0-pad)));x1=min(w,int(np.ceil(x1+pad)));y1=min(h,int(np.ceil(y1+pad)))
   patch=feat[y0:y1,x0:x1]
   if patch.shape[0]<7 or patch.shape[1]<7 or patch.shape[0]>=h or patch.shape[1]>=w:continue
   templates.append(dict(kind="current_reference",prototype_id=f"current-{ri+1}",family_id="current_image",template=patch,reference_index=ri+1,stats=ref,reliability=1.0))
  return templates
 def _library_templates(self):
  if not self.use_library.get():return []
  data=self._load_library();out=[]
  protos=list(data.get("prototypes",[]))
  protos.sort(key=lambda p:(int(p.get("accepted_count",1))-int(p.get("rejected_count",0)),p.get("last_confirmed_at",p.get("created_at",""))),reverse=True)
  strong=[p for p in protos if int(p.get("accepted_count",1))>=2 and int(p.get("rejected_count",0))==0]
  # If the user has confirmed the same egg-like appearance repeatedly, that is
  # much better training evidence than a large pile of one-off accepted points.
  if len(strong)>=5:protos=strong
  try:max_protos=max(0,min(24,int(float(self.dial_float("max_library_prototypes",8) or 8))))
  except Exception:max_protos=8
  for p in protos[:max_protos]:
   patch=self._decode_patch(p.get("template_png",""))
   if patch is None or patch.shape[0]<7 or patch.shape[1]<7:continue
   accepted=max(1,int(p.get("accepted_count",1)));rejected=int(p.get("rejected_count",0))
   reliability=accepted/max(accepted+rejected,1)
   if reliability<0.35:continue
   out.append(dict(kind="lab_library",prototype_id=p.get("id","library"),family_id=p.get("family_id","general"),
                   template=patch,reference_index=p.get("id","library"),stats=p.get("stats",{}),reliability=reliability))
  return out
 def _trap_templates(self):
  if not self.use_library.get():return []
  data=self._load_library();out=[]
  try:max_traps=max(0,min(32,int(float(self.dial_float("max_library_prototypes",8) or 8))*2))
  except Exception:max_traps=16
  for p in data.get("false_positive_traps",[])[-max_traps:]:
   patch=self._decode_patch(p.get("template_png",""))
   if patch is not None and patch.shape[0]>=7 and patch.shape[1]>=7:
    out.append(cv2.resize(np.asarray(patch,np.uint8),(32,32),interpolation=cv2.INTER_AREA))
  return out
 def _trap_match_score(self,patch,traps):
  if patch is None or not traps:return 0.0
  p=cv2.resize(np.asarray(patch,np.uint8),(32,32),interpolation=cv2.INTER_AREA)
  best=0.0
  for tt in traps:
   try:best=max(best,float(cv2.matchTemplate(p,tt,cv2.TM_CCOEFF_NORMED)[0,0]))
   except Exception:pass
  return best
 def _template_matches_from_sources(self,im,sources):
  if not sources:return pd.DataFrame()
  thresh=self.dial_float("template_match",None)
  if thresh is None:thresh=.42
  feat=self._feature_image(im);roi_mask=np.ones(feat.shape,np.uint8)*255
  if self.roi:roi_mask=np.zeros(feat.shape,np.uint8);cv2.fillPoly(roi_mask,[np.round(self.roi).astype(np.int32)],255)
  rows=[];h,w=feat.shape
  gray=gray8(im)
  min_local=self.dial_float("local_contrast")
  min_bright=self.dial_float("bright_contrast")
  min_dark=self.dial_float("dark_contrast")
  min_span=self.dial_float("intensity_span")
  for src in sources:
   templ=np.asarray(src["template"],np.uint8);stats=src.get("stats",{})
   for rot in (0,1,2,3):
    t=np.ascontiguousarray(np.rot90(templ,rot)) if rot else templ
    if t.shape[0]>=h or t.shape[1]>=w:continue
    res=cv2.matchTemplate(feat,t,cv2.TM_CCOEFF_NORMED)
    # Template matches are only proposals.  Current-image examples are powerful
    # but can otherwise turn every egg-sized patch of agar texture into a
    # candidate, so they are deliberately stricter than the visible dial floor.
    if str(src.get("kind",""))=="current_reference":
     local_thresh=max(float(thresh),.52)
    else:
     reliability=float(src.get("reliability",1.0))
     # Learned library examples are useful, but phase/agar texture creates many
     # egg-like local patches.  Keep library proposals conservative; exact
     # reviewed-image state carries confirmed eggs, distinct images do not.
     local_thresh=max(float(thresh),.60-.04*min(reliability,1.0))
    ys,xs=np.where(res>=local_thresh)
    per_source_limit=40 if str(src.get("kind",""))=="current_reference" else 18
    order=np.argsort(res[ys,xs])[::-1][:per_source_limit] if len(xs) else []
    for idx in order:
     yy=int(ys[idx]);xx=int(xs[idx]);score=float(res[yy,xx])
     cx=xx+t.shape[1]/2;cy=yy+t.shape[0]/2
     if 0<=int(cy)<h and 0<=int(cx)<w and roi_mask[int(cy),int(cx)]==0:continue
     length_um=float(stats.get("length_um",self.egg_length_um or 50))
     width_um=float(stats.get("width_um",self.egg_width_um or 30))
     angle=float(stats.get("angle_deg",0))+rot*90
     major_px=max(3,length_um/max(float(self.scale or 1),1e-6))
     minor_px=max(3,width_um/max(float(self.scale or 1),1e-6))
     mean_intensity,local_background,local_contrast,bright_contrast,dark_contrast,intensity_span=_intensity_context(
      gray,cx,cy,major_px,minor_px,angle,roi_mask)
     if min_local is not None and local_contrast<float(min_local):continue
     if min_bright is not None and bright_contrast<float(min_bright):continue
     if min_dark is not None and dark_contrast<float(min_dark):continue
     if min_span is not None and intensity_span<float(min_span):continue
     # A candidate found from a marked example should preserve at least part of
     # the reference egg's steep bright/dark edge signature.  Size and rotation
     # alone are not enough on textured agar.
     ref_b=float(stats.get("bright_contrast",0) or 0);ref_d=float(stats.get("dark_contrast",0) or 0);ref_s=float(stats.get("intensity_span",0) or 0)
     if str(src.get("kind",""))=="current_reference":
      if ref_b and bright_contrast<ref_b*.45:continue
      if ref_d and dark_contrast<ref_d*.45:continue
      if ref_s and intensity_span<ref_s*.45:continue
     rows.append(dict(x=float(cx),y=float(cy),length_um=float(stats.get("length_um",self.egg_length_um or 50)),
                      width_um=float(stats.get("width_um",self.egg_width_um or 30)),angle_deg=angle,
                      score=float(-score),aspect_ratio=float(stats.get("aspect_ratio",1.5)),solidity=np.nan,
                      ellipse_fill=np.nan,rim_gradient=np.nan,edge_polarity=np.nan,mean_intensity=float(mean_intensity),
                      local_background=float(local_background),local_contrast=float(local_contrast),
                      bright_contrast=float(bright_contrast),dark_contrast=float(dark_contrast),
                      intensity_span=float(intensity_span),template_score=score,
                      prototype_id=str(src.get("prototype_id","")),prototype_family=str(src.get("family_id","")),
                      template_reference=str(src.get("reference_index","")),source=str(src.get("kind","reference_template"))))
  if not rows:return pd.DataFrame()
  rows.sort(key=lambda r:r["score"]);kept=[];gate=max(5,(self.egg_width_um or 30)/self.scale*.75)
  for r in rows:
   if all(np.hypot(r["x"]-k["x"],r["y"]-k["y"])>gate for k in kept):kept.append(r)
  return pd.DataFrame(kept[:80])
 def _template_candidates(self,im):
  sources=self._reference_templates(im)+self._library_templates()
  return self._template_matches_from_sources(im,sources)
 def _candidate_vote_score(self,row,egg_len,egg_wid):
  """Score a proposed egg by independent, peer-reviewable evidence.

  The first validation pass showed that contrast features separate true eggs
  from egg-like debris better than template matching or single shape filters.
  Votes therefore keep size/shape as useful context, but require contrast
  support by default.
  """
  def f(k,default=np.nan):
   try:return float(row.get(k,default))
   except Exception:return default
  def ok(v):
   try:return np.isfinite(float(v))
   except Exception:return False
  votes=[];contrast=[]
  major_min=self.dial_float("major_min",max(1.0,egg_len*.80));major_max=self.dial_float("major_max",egg_len*1.40)
  minor_min=self.dial_float("minor_min",max(1.0,egg_wid*.80));minor_max=self.dial_float("minor_max",egg_wid*1.45)
  aspect_min=max(1.10,self.dial_float("aspect_min",1.25));aspect_max=min(2.60,self.dial_float("aspect_max",2.10))
  L=f("length_um");W=f("width_um");aspect=f("aspect_ratio")
  if ok(L) and major_min<=L<=major_max:votes.append("size_major")
  if ok(W) and minor_min<=W<=minor_max:votes.append("size_minor")
  if ok(aspect) and aspect_min<=aspect<=aspect_max:votes.append("oval_aspect")
  solidity=f("solidity");fill=f("ellipse_fill")
  if ok(solidity) and ok(fill) and solidity>=self.dial_float("solidity",.82) and self.dial_float("fill_min",.55)<=fill<=self.dial_float("fill_max",1.18):votes.append("ellipse_fit")
  rim=f("rim_gradient")
  if ok(rim) and rim>=max(.09,self.dial_float("rim",.045)):votes.append("rim_gradient")
  local=f("local_contrast");bright=f("bright_contrast");dark=f("dark_contrast");span=f("intensity_span")
  if ok(local) and local>=self.dial_float("local_contrast",.040):votes.append("local_contrast");contrast.append("local_contrast")
  if ok(bright) and bright>=self.dial_float("bright_contrast",.140):votes.append("bright_edge");contrast.append("bright_edge")
  if ok(dark) and dark>=self.dial_float("dark_contrast",.140):votes.append("dark_edge");contrast.append("dark_edge")
  if ok(span) and span>=self.dial_float("intensity_span",.320):votes.append("span");contrast.append("span")
  templ=f("template_score")
  source=str(row.get("source",""))
  # Template matching was useful as a search tool but weak as evidence unless
  # it is either a current-image reference or agrees with contrast.
  if ok(templ) and templ>=self.dial_float("template_match",.78) and (source=="current_reference" or len(contrast)>=2):
   votes.append("template")
  return len(votes),len(contrast),";".join(votes)
 def _annotate_reject_memory(self,im,d,egg_len,egg_wid):
  """Add learned false-positive similarity scores before the vote gate.

  Rejected cyan candidates are useful negative teaching examples.  They should
  not erase human-added/reference eggs, but they should make the module more
  skeptical of debris or agar texture that repeatedly fooled it.
  """
  if not len(d):
   return d
  traps=self._trap_templates()
  d=d.copy()
  if not traps:
   d["false_positive_match_score"]=0.0
   d["false_positive_memory_hit"]=False
   return d
  scores=[]
  for _,row in d.iterrows():
   patch=self._candidate_template_patch(im,float(row["x"]),float(row["y"]),
    float(row.get("length_um",egg_len)) if pd.notna(row.get("length_um",np.nan)) else egg_len,
    float(row.get("width_um",egg_wid)) if pd.notna(row.get("width_um",np.nan)) else egg_wid)
   scores.append(float(self._trap_match_score(patch,traps)))
  thresh=float(self.dial_float("false_positive_match",.72) or .72)
  d["false_positive_match_score"]=scores
  d["false_positive_memory_hit"]=d["false_positive_match_score"].astype(float)>=thresh
  return d
 def _score_and_filter_candidates(self,d,egg_len,egg_wid):
  if not len(d):return d
  d=d.copy()
  rows=[]
  for _,row in d.iterrows():rows.append(self._candidate_vote_score(row,egg_len,egg_wid))
  d["egg_votes"]=[r[0] for r in rows];d["contrast_votes"]=[r[1] for r in rows];d["vote_reasons"]=[r[2] for r in rows]
  min_votes=int(float(self.dial_float("min_votes",5) or 5));min_contrast=int(float(self.dial_float("min_contrast_votes",2) or 2))
  source=d.get("source",pd.Series([""]*len(d))).astype(str)
  seed=source.isin(["reference_seed","prior_review"])
  high=(d["egg_votes"]>=min_votes)&(d["contrast_votes"]>=min_contrast)
  maybe=(d["egg_votes"]>=max(3,min_votes-2))&(d["contrast_votes"]>=max(1,min_contrast-1))
  reject_hit=d.get("false_positive_memory_hit",pd.Series([False]*len(d))).fillna(False).astype(bool)
  d["candidate_tier"]=np.where(seed,"manual_seed",
   np.where(reject_hit,"learned_non_egg",
    np.where(high,"high_confidence",np.where(maybe,"low_confidence","filtered"))))
  keep=seed|(high&~reject_hit)
  d=d.loc[keep].copy()
  if len(d):
   d["score"]=d["score"].astype(float)-d["egg_votes"].astype(float)*.20-d["contrast_votes"].astype(float)*.15
   d=d.sort_values(["candidate_tier","egg_votes","contrast_votes","score"],ascending=[True,False,False,True]).reset_index(drop=True)
  return d
 def _detect_review_candidates(self,im):
   egg_len=self.egg_length_um or 50;egg_wid=self.egg_width_um or 30
   params=dict(length_um_min=self.dial_float("major_min"),length_um_max=self.dial_float("major_max"),
               width_um_min=self.dial_float("minor_min"),width_um_max=self.dial_float("minor_max"),
               min_aspect=self.dial_float("aspect_min",1.15),max_aspect=self.dial_float("aspect_max",2.60),
               min_solidity=self.dial_float("solidity",.82),min_ellipse_fill=self.dial_float("fill_min",.55),
               max_ellipse_fill=self.dial_float("fill_max",1.18),min_rim_gradient=self.dial_float("rim",.045),
               min_mean_intensity=self.dial_float("bright_min"),max_mean_intensity=self.dial_float("bright_max"),
               min_local_contrast=self.dial_float("local_contrast"),
               min_bright_contrast=self.dial_float("bright_contrast"),
               min_dark_contrast=self.dial_float("dark_contrast"),
               min_intensity_span=self.dial_float("intensity_span"),
               reference_prototypes=[{k:r.get(k) for k in ("length_um","width_um","aspect_ratio","local_contrast","bright_contrast","dark_contrast","intensity_span")} for r in self.reference_eggs])
   d=detect_eggs(im,self.scale,self.roi,length_um=egg_len,width_um=egg_wid,tolerance=float(self.tol.get())/100,**params)
   if len(d):d=d.copy();d["source"]="automatic"
   td=self._template_candidates(im)
   if len(td):d=pd.concat([d,td],ignore_index=True,sort=False)
   if len(d):
    d=d.sort_values("score").reset_index(drop=True);kept=[];gate=max(5,egg_wid/self.scale*.65)
    for _,row in d.iterrows():
     if all(np.hypot(float(row.x)-float(k.x),float(row.y)-float(k.y))>gate for k in kept):kept.append(row)
    d=pd.DataFrame(kept).reset_index(drop=True) if kept else d.iloc[0:0].copy()
   if len(d):d=self._annotate_reject_memory(im,d,egg_len,egg_wid)
   seg=find_accepted_config(self.source.get(),"endpoint_egg_counting")
   if seg is not None and len(d):
    mask=segment_frame(im,int(self.frame.get()),seg)
    keep=[bool(mask[int(round(y)),int(round(x))]) if 0<=int(round(y))<mask.shape[0] and 0<=int(round(x))<mask.shape[1] else False for x,y in d[["x","y"]].to_numpy()]
    d=d[np.asarray(keep,bool)].reset_index(drop=True)
   refs=self._reference_candidate();add_refs=[]
   for ref in refs:
    if not len(d) or all(np.hypot(ref["x"]-float(row.x),ref["y"]-float(row.y))>max(5,egg_wid/self.scale*.6) for _,row in d.iterrows()):
     add_refs.append(ref)
   if add_refs:d=pd.concat([pd.DataFrame(add_refs),d],ignore_index=True)
   if len(d) and "false_positive_match_score" not in d.columns:
    d=self._annotate_reject_memory(im,d,egg_len,egg_wid)
   if len(d):d=self._score_and_filter_candidates(d,egg_len,egg_wid)
   return d,egg_len,egg_wid,bool(seg)
 def refresh_open_review(self):
  ctx=self._review_ctx
  if ctx is None:return
  try:
   proc=ctx.get("process_log")
   if proc:
    with proc.timed("Refresh proposals from dials","Re-run egg cues and vote filter using the current dials."):
     d,_,_,_=self._detect_review_candidates(ctx["im"])
   else:
    d,_,_,_=self._detect_review_candidates(ctx["im"])
   ctx["d"]=d;ctx["points"]=d[["x","y"]].to_numpy().tolist() if len(d) else [];ctx["accepted"]=[False]*len(ctx["points"]);ctx["review_state"]=["proposed"]*len(ctx["points"])
   ctx["redraw"]()
   panel=ctx.get("process_panel")
   if panel:panel.refresh()
   self.status.set(f"Open review refreshed from dials: {len(ctx['points'])} candidate(s).")
  except Exception as e:self.status.set(f"Could not refresh open review: {e}")
 def _candidate_template_patch(self,im,x,y,length_um=None,width_um=None):
  feat=self._feature_image(im);h,w=feat.shape
  major_px=max(9,float(length_um or self.egg_length_um or 50)/float(self.scale or 1))
  minor_px=max(7,float(width_um or self.egg_width_um or 30)/float(self.scale or 1))
  half=int(round(max(major_px,minor_px)*.95))
  x=int(round(x));y=int(round(y))
  x0=max(0,x-half);x1=min(w,x+half+1);y0=max(0,y-half);y1=min(h,y+half+1)
  patch=feat[y0:y1,x0:x1]
  if patch.shape[0]<7 or patch.shape[1]<7:return None
  return patch
 def _merge_or_add_prototype(self,data,proto):
  """Keep the library finite: similar accepted eggs reinforce an existing prototype."""
  patch=self._decode_patch(proto.get("template_png",""))
  if patch is None:return
  patch32=cv2.resize(np.asarray(patch,np.uint8),(32,32),interpolation=cv2.INTER_AREA)
  best=None;best_score=-1.0
  for old in data.get("prototypes",[]):
   oldpatch=self._decode_patch(old.get("template_png",""))
   if oldpatch is None:continue
   old32=cv2.resize(np.asarray(oldpatch,np.uint8),(32,32),interpolation=cv2.INTER_AREA)
   try:
    score=float(cv2.matchTemplate(patch32,old32,cv2.TM_CCOEFF_NORMED)[0,0])
   except Exception:
    continue
   if score>best_score:best_score=score;best=old
  if best is not None and best_score>=0.82:
   best["accepted_count"]=int(best.get("accepted_count",1))+1
   best["last_confirmed_at"]=proto["created_at"]
   best["last_context"]=proto.get("context",{})
   return
  data.setdefault("prototypes",[]).append(proto)
  # Prefer frequently confirmed examples and keep the JSON from growing forever.
  data["prototypes"].sort(key=lambda p:(int(p.get("accepted_count",1))-int(p.get("rejected_count",0)),p.get("last_confirmed_at",p.get("created_at",""))),reverse=True)
  data["prototypes"]=data["prototypes"][:120]
 def _learn_from_review(self,ctx,review,out):
  if not self.learn_library.get():return {"library_learning":"disabled"}
  data=self._load_library();now=datetime.datetime.now().isoformat(timespec="seconds");context=self._source_context(ctx["im"])
  accepted_added=0;rejected_penalized=0;traps_added=0;pending_ignored=0
  for i,row in review.iterrows():
   state=str(row.get("review_state","accepted" if bool(row.get("accepted",False)) else "rejected")).lower()
   if state in ("pending","proposed"):
    pending_ignored+=1;continue
   x=float(row["x"]);y=float(row["y"]);accepted=bool(row["accepted"]) and state in ("accepted","manual")
   cand=ctx["d"].iloc[i] if i<len(ctx["d"]) else None
   proto_id=str(cand.get("prototype_id","")) if cand is not None else ""
   if accepted:
    length_um=float(cand.get("length_um",ctx["egg_len"])) if cand is not None else float(ctx["egg_len"])
    width_um=float(cand.get("width_um",ctx["egg_wid"])) if cand is not None else float(ctx["egg_wid"])
    patch=self._candidate_template_patch(ctx["im"],x,y,length_um,width_um)
    if patch is None:continue
    proto=dict(id=str(uuid.uuid4()),family_id=context["source_name"],created_at=now,last_confirmed_at=now,
               accepted_count=1,rejected_count=0,context=context,
               stats=dict(length_um=length_um,width_um=width_um,
                          aspect_ratio=float(cand.get("aspect_ratio",length_um/max(width_um,1e-6))) if cand is not None else length_um/max(width_um,1e-6),
                          mean_intensity=float(cand.get("mean_intensity",np.nan)) if cand is not None else np.nan,
                          local_background=float(cand.get("local_background",np.nan)) if cand is not None else np.nan,
                          local_contrast=float(cand.get("local_contrast",np.nan)) if cand is not None else np.nan,
                          bright_contrast=float(cand.get("bright_contrast",np.nan)) if cand is not None else np.nan,
                          dark_contrast=float(cand.get("dark_contrast",np.nan)) if cand is not None else np.nan,
                          intensity_span=float(cand.get("intensity_span",np.nan)) if cand is not None else np.nan),
               template_png=self._encode_patch(patch))
    self._merge_or_add_prototype(data,proto);accepted_added+=1
   elif state=="rejected":
    if proto_id:
     for p in data.get("prototypes",[]):
      if str(p.get("id",""))==proto_id:
       p["rejected_count"]=int(p.get("rejected_count",0))+1;p["last_rejected_at"]=now;rejected_penalized+=1;break
    patch=self._candidate_template_patch(ctx["im"],x,y,
     float(cand.get("length_um",ctx["egg_len"])) if cand is not None else ctx["egg_len"],
     float(cand.get("width_um",ctx["egg_wid"])) if cand is not None else ctx["egg_wid"])
    if patch is not None and len(data.setdefault("false_positive_traps",[]))<200:
     data["false_positive_traps"].append(dict(id=str(uuid.uuid4()),created_at=now,context=context,source=str(row.get("source","")),
                                              template_png=self._encode_patch(patch)))
     traps_added+=1
  self._save_library(data)
  (out/"egg_prototype_learning_summary.json").write_text(json.dumps(dict(accepted_prototypes_added=accepted_added,
   rejected_library_prototypes_penalized=rejected_penalized,false_positive_traps_added=traps_added,
   pending_proposals_ignored=pending_ignored,library_path=str(self._library_path()),human_approved=True),indent=2),encoding="utf-8")
  return {"library_learning":"human_approved","accepted_prototypes_added":accepted_added,
          "rejected_library_prototypes_penalized":rejected_penalized,"false_positive_traps_added":traps_added,
          "pending_proposals_ignored":pending_ignored,"library_path":str(self._library_path())}
 def _save_review_results(self,ctx):
   im=ctx["im"];d=ctx["d"];points=ctx["points"];accepted=ctx["accepted"];egg_len=ctx["egg_len"];egg_wid=ctx["egg_wid"];seg=ctx["seg"]
   out=Path(self.source.get()).parent/f"{Path(self.source.get()).stem}_egg_count_results";out.mkdir(parents=True,exist_ok=True)
   d.to_csv(out/"automatic_candidates.csv",index=False)
   review_states=ctx.get("review_state",["accepted" if a else "rejected" for a in accepted])
   review=pd.DataFrame([dict(x=p[0],y=p[1],accepted=a,review_state=str(review_states[i]) if i<len(review_states) else ("accepted" if a else "rejected"),source=str(d.iloc[i].get("source","automatic")) if i<len(d) else "manual_add",
                             prototype_id=str(d.iloc[i].get("prototype_id","")) if i<len(d) else "",
                             prototype_family=str(d.iloc[i].get("prototype_family","")) if i<len(d) else "",
                             template_score=float(d.iloc[i].get("template_score",np.nan)) if i<len(d) else np.nan,
                             egg_votes=int(d.iloc[i].get("egg_votes",0)) if i<len(d) and pd.notna(d.iloc[i].get("egg_votes",np.nan)) else 0,
                             contrast_votes=int(d.iloc[i].get("contrast_votes",0)) if i<len(d) and pd.notna(d.iloc[i].get("contrast_votes",np.nan)) else 0,
                             candidate_tier=str(d.iloc[i].get("candidate_tier","manual_add")) if i<len(d) else "manual_add",
                             false_positive_match_score=float(d.iloc[i].get("false_positive_match_score",np.nan)) if i<len(d) else np.nan,
                             false_positive_memory_hit=bool(d.iloc[i].get("false_positive_memory_hit",False)) if i<len(d) else False,
                             vote_reasons=str(d.iloc[i].get("vote_reasons","")) if i<len(d) else "")
                        for i,(p,a) in enumerate(zip(points,accepted))])
   review.to_csv(out/"reviewed_eggs.csv",index=False)
   self._save_overlays(out,im,d,review)
   learning=self._learn_from_review(ctx,review,out)
   method=self.calibration_method or "declared";scale_source="two_point_calibration" if method=="segmented_worm_trace" else method
   acquisition=AcquisitionMetadata(None,"not_applicable",self.scale,scale_source,None,"not_applicable").validate()
   state_counts=review["review_state"].value_counts().to_dict() if len(review) and "review_state" in review else {}
   meta={**acquisition.as_columns(),"reviewed_egg_count":int(review.accepted.sum()) if len(review) else 0,"accepted_egg_count":int(state_counts.get("accepted",0)+state_counts.get("manual",0)),"manual_egg_count":int(state_counts.get("manual",0)),"proposed_unreviewed_egg_count":int(state_counts.get("proposed",state_counts.get("pending",0))),"rejected_egg_count":int(state_counts.get("rejected",0)),"automatic_candidate_count":len(d),"expected_egg_length_um":egg_len,"expected_egg_width_um":egg_wid,"egg_detection_dials":{k:v.get() for k,v in self.dials.items()},"use_lab_egg_library":bool(self.use_library.get()),"contribute_reviewed_eggs_to_library":bool(self.learn_library.get()),"prototype_learning":learning,"reference_egg_used":bool(self.egg_length_um and self.egg_width_um),"reference_egg_points":self.reference_egg_points,"reference_eggs":self.reference_eggs,"frame":int(self.frame.get()),"review_required":True,"segmentation_review_applied":bool(seg),"calibration_method":method,"calibration_length_px":self.calibration_length_px,"declared_worm_length_mm":float(self.worm_length.get()) if method=="segmented_worm_trace" else None,"calibration_points":self.calibration_points}
   if ctx.get("process_log") is not None:
    meta["process_steps"]=ctx["process_log"].steps
    (out/"process_steps.json").write_text(json.dumps(ctx["process_log"].steps,indent=2),encoding="utf-8")
   (out/"egg_count_summary.json").write_text(json.dumps(meta,indent=2),encoding="utf-8");pd.DataFrame([meta]).to_csv(out/"egg_count_summary.csv",index=False)
   try:
    vote_counts=d["egg_votes"].value_counts().sort_index().to_dict() if len(d) and "egg_votes" in d else {}
    tier_counts=d["candidate_tier"].value_counts().to_dict() if len(d) and "candidate_tier" in d else {}
    reject_hits=int(d["false_positive_memory_hit"].sum()) if len(d) and "false_positive_memory_hit" in d else 0
    write_decision_manifest(out,"endpoint_egg_counting",
     method_note=("Egg proposals are scored by a transparent vote across egg-like cues: size, oval shape, ellipse fill, "
                  "local contrast, bright/dark edge contrast, brightness span, rim gradient, and optional prototype-template similarity. "
                  "Human-rejected examples are stored as false-positive traps and can suppress future look-alikes. "
                  "Cyan proposals are not counted as final eggs until the reviewer accepts them; manual orange eggs are treated as human-added positives."),
     summary={**meta,"automatic_candidate_tiers":tier_counts,"automatic_candidate_vote_histogram":vote_counts,
              "vote_policy":vote_policy_summary(
               ["size_major","size_minor","oval_aspect","ellipse_fit","rim_gradient","local_contrast","bright_edge","dark_edge","brightness_span","template"],
               required_votes=self.dials["min_votes"].get(),
               required_contrast_votes=self.dials["min_contrast_votes"].get(),
               vetoes=["false_positive_memory_hit"],human_review=True),
              "minimum_total_votes_for_default_proposal":self.dials["min_votes"].get(),
              "minimum_contrast_votes_for_default_proposal":self.dials["min_contrast_votes"].get(),
              "false_positive_memory_threshold":self.dials["false_positive_match"].get(),
              "false_positive_memory_hits_in_exported_candidates":reject_hits},
     decision_files={"automatic_candidates_csv":"automatic_candidates.csv","reviewed_eggs_csv":"reviewed_eggs.csv",
                     "summary_json":"egg_count_summary.json","learning_summary_json":"egg_prototype_learning_summary.json",
                     "accepted_overlay":"reviewed_eggs_overlay.png","all_review_overlay":"reviewed_eggs_all_states.png",
                     "process_timing_json":"process_steps.json"},
     fields={"egg_votes":"Number of independent egg-like cues that supported this candidate.",
             "contrast_votes":"Votes specifically from local image contrast/edge cues.",
             "vote_reasons":"Semicolon-separated names of the cues that passed.",
             "candidate_tier":"manual_seed, high_confidence, low_confidence, or filtered before review.",
             "false_positive_match_score":"Similarity to human-rejected non-egg examples in the shared egg library.",
             "false_positive_memory_hit":"True when the candidate was suppressed or flagged by reject-memory.",
             "review_state":"accepted, rejected, proposed/unreviewed, or manual human-added egg."},
     color_legend={"cyan":"module proposal not yet evaluated","green":"accepted by reviewer","red":"rejected by reviewer",
                   "orange":"manual human-added egg/reference/training example"},
     caveats=["The prototype library assists matching but is not allowed to override weak contrast evidence by itself.",
              "Reject-memory is deliberately conservative and never suppresses a current human reference seed.",
              "Coordinates restored from a prior reviewed_eggs.csv are exact same-source review state, not generalized learning.",
              "Use reviewed_eggs.csv for final counts; automatic_candidates.csv is the detector's hypothesis list."])
   except Exception as e:
    (out/"decision_transparency_error.txt").write_text(str(e),encoding="utf-8")
   self.status.set(f"Reviewed count: {meta['reviewed_egg_count']}. Results: {out}");messagebox.showinfo("Egg count complete",self.status.get())
 def _review_results_dir(self):
  src=Path(self.source.get())
  return src.parent/f"{src.stem}_egg_count_results"
 def _find_prior_review_file(self):
  """Only reload reviewed state for the exact same source/result folder.

  Adjacent frames are distinct samples in this module.  A new image may benefit
  from the shared egg prototype library, but it must not silently inherit the
  previous image's accepted/rejected coordinates.
  """
  exact=self._review_results_dir()/"reviewed_eggs.csv"
  if exact.exists():return exact,"exact_source"
  return None,"none"
 def _load_prior_review_state(self,d):
  """Reload same-image reviewed eggs before proposing new detections.

  The prototype library is intentionally probabilistic; the reviewed CSV is not.
  If the same source image/stack frame was already reviewed, those human states
  should be restored exactly, then fresh automatic candidates can be appended as
  cyan proposals if they are not near a saved point.
  """
  prior,prior_kind=self._find_prior_review_file()
  if prior is None or not prior.exists():
   return d,d[["x","y"]].to_numpy().tolist() if len(d) else [],[False]*len(d),["proposed"]*len(d),0
  try:
   old=read_table(prior)
  except Exception:
   return d,d[["x","y"]].to_numpy().tolist() if len(d) else [],[False]*len(d),["proposed"]*len(d),0
  if not len(old) or "x" not in old or "y" not in old:
   return d,d[["x","y"]].to_numpy().tolist() if len(d) else [],[False]*len(d),["proposed"]*len(d),0
  rows=[];points=[];accepted=[];states=[];claimed=set()
  max_dist=max(10.0,float(self.dial_float("major_max",self.egg_length_um or 50.0) or 50.0)/(max(float(self.scale or 1.0),1e-6))*0.65)
  for _,row in old.iterrows():
   try:x=float(row["x"]);y=float(row["y"])
   except Exception:continue
   state=str(row.get("review_state","accepted" if bool(row.get("accepted",False)) else "rejected")).lower()
   if state in ("pending","proposal","unreviewed"):state="proposed"
   if state not in ("accepted","rejected","manual","proposed"):state="accepted" if bool(row.get("accepted",False)) else "rejected"
   points.append([x,y]);states.append(state);accepted.append(state in ("accepted","manual"))
   match_i=None
   if len(d):
    dist=np.hypot(d["x"].astype(float).to_numpy()-x,d["y"].astype(float).to_numpy()-y)
    if len(dist):
     j=int(np.argmin(dist))
     if float(dist[j])<=max_dist and j not in claimed:match_i=j;claimed.add(j)
   if match_i is not None:
    rec=d.iloc[match_i].to_dict();rec["x"]=x;rec["y"]=y;rec["review_state"]=state;rec["accepted"]=state in ("accepted","manual")
   else:
    rec={k:row.get(k,np.nan) for k in old.columns}
    rec.setdefault("score",np.nan);rec.setdefault("source","prior_review")
    rec["x"]=x;rec["y"]=y;rec["review_state"]=state;rec["accepted"]=state in ("accepted","manual")
   rows.append(rec)
  new_proposal_count=0
  max_new_proposals=40 if points else 999999
  for i,row in d.iterrows():
   if new_proposal_count>=max_new_proposals:break
   if i in claimed:continue
   x=float(row["x"]);y=float(row["y"])
   if points and min(np.hypot(x-p[0],y-p[1]) for p in points)<=max_dist:continue
   rec=row.to_dict();rec["review_state"]="proposed";rec["accepted"]=False
   rows.append(rec);points.append([x,y]);accepted.append(False);states.append("proposed");new_proposal_count+=1
  merged=pd.DataFrame(rows) if rows else d.copy()
  return merged,points,accepted,states,len(points)
 def review(self):
  try:
   if not self.scale:raise ValueError("Calibrate the scale first.")
   proc=ProcessLog("WINK egg process - press 'h' to hide/show")
   with proc.timed("Load image/frame","Open the selected source and extract the reviewed frame."):
    im=self.load()
   with proc.timed("Detect egg-like candidates","Generate shape/contrast/template candidates, then score them by transparent egg votes."):
    d,egg_len,egg_wid,seg=self._detect_review_candidates(im)
   with proc.timed("Restore exact prior review","Reload accepted/rejected/manual points only for this exact source if available."):
    d,points,accepted,review_state,prior_count=self._load_prior_review_state(d)
   proc.add("Human review","Left click accepts cyan eggs, right click rejects, Shift+left adds a manual orange egg. Press 'c' for controls and 'h' for the hood.","ready")
   wb=ReviewWorkbench(self,"Endpoint egg review",proc,width=1380,height=880)
   fig,ax=wb.fig,wb.ax
   ax.imshow(gray8(im),cmap="gray");ax.set_title("Cyan = module proposal. Orange = manually added. Left click = accept/green. Right click = reject/red. Shift+left click = add orange egg. Press h = hide/show process.")
   scat=ax.scatter([p[0] for p in points],[p[1] for p in points],s=90,facecolors="none",linewidths=2)
   ctx={"im":im,"d":d,"points":points,"accepted":accepted,"review_state":review_state,"fig":fig,"ax":ax,"scat":scat,"egg_len":egg_len,"egg_wid":egg_wid,"seg":seg,"process_log":proc,"process_panel":wb,"workbench":wb}
   self._review_ctx=ctx
   def add_controls():
    wb.clear_controls()
    wb.set_status("Review eggs in the center canvas. Keys: c hides controls; h hides hood.")
    wb.add_control_label("Review actions")
    wb.add_control_label("Left click: accept. Right click: reject. Shift+left: add egg. Toolbar below image: zoom/pan/save.")
    wb.add_control_button("Refresh proposals from dials",self.refresh_open_review)
    wb.add_control_button("Save and close",wb.close)
    wb.add_control_button("Hide controls (c)",wb.toggle_controls)
    wb.add_control_separator()
    wb.add_control_label("Live egg dials")
    wb.add_control_label("These are the main filters; changes refresh the open review after a short pause.")
    rows=[
     ("Min votes","min_votes"),("Contrast votes","min_contrast_votes"),
     ("Major min","major_min"),("Major max","major_max"),
     ("Minor min","minor_min"),("Minor max","minor_max"),
     ("Bright edge","bright_contrast"),("Dark edge","dark_contrast"),
     ("Span","intensity_span"),("Template","template_match"),
     ("Reject memory","false_positive_match")]
    for lab,key in rows:
     wb.add_labeled_entry(lab,self.dials[key],width=10)
    wb.add_control_separator()
    ttk.Checkbutton(wb.controls_frame,text="Use learned library",variable=self.use_library).pack(anchor="w",padx=6,pady=3)
    ttk.Checkbutton(wb.controls_frame,text="Teach library from this review",variable=self.learn_library).pack(anchor="w",padx=6,pady=3)
   add_controls()
   if prior_count:
    self.status.set(f"Seeded review with {prior_count} prior egg mark(s); added {review_state.count('proposed')} cautious cyan proposal(s).")
   def redraw():
    colors=[]
    facecolors=[]
    for i,a in enumerate(ctx["accepted"]):
     # LOWERCASED, TO MATCH THE EXPORT. The overlay writer lowercases the
     # state and this view did not, so the same egg could read cyan
     # (unreviewed) on screen and green (accepted) in the saved overlay -
     # two colours for one fact, and the screen is where the person decides.
     state=str(ctx.get("review_state",["proposed"]*len(ctx["accepted"]))[i]).lower()
     if state=="accepted":colors.append("lime");facecolors.append("lime")
     elif state=="rejected":colors.append("red");facecolors.append("none")
     elif state=="manual":colors.append("orange");facecolors.append("orange")
     else:colors.append("cyan");facecolors.append("none")
    pts=np.asarray(ctx["points"],float).reshape(-1,2) if ctx["points"] else np.empty((0,2))
    ctx["scat"].set_offsets(pts);ctx["scat"].set_edgecolors(colors);ctx["scat"].set_facecolors(facecolors);wb.draw_idle()
   ctx["redraw"]=redraw;redraw()
   def click(e):
    if e.inaxes!=ax or e.xdata is None:return
    if e.key=="shift" and e.button==1:
     ctx["points"].append([e.xdata,e.ydata]);ctx["accepted"].append(True);ctx["review_state"].append("manual")
     proc.add("Manual egg added",f"x={e.xdata:.1f}, y={e.ydata:.1f}","review")
    elif ctx["points"]:
     j=int(np.argmin([np.hypot(e.xdata-p[0],e.ydata-p[1]) for p in ctx["points"]]))
     if e.button==1:
      ctx["accepted"][j]=True;ctx["review_state"][j]="accepted"
      proc.add("Accepted egg",f"candidate {j+1}, x={ctx['points'][j][0]:.1f}, y={ctx['points'][j][1]:.1f}","review")
     elif e.button==3:
      ctx["accepted"][j]=False;ctx["review_state"][j]="rejected"
      proc.add("Rejected candidate",f"candidate {j+1}, x={ctx['points'][j][0]:.1f}, y={ctx['points'][j][1]:.1f}","review")
    redraw()
    wb.refresh_hood()
   def close(_):
    if self._review_ctx is not ctx:return
    with proc.timed("Save review and audit trail","Write reviewed eggs, overlays, learning update, timing log, and decision manifest."):
     self._save_review_results(ctx)
    try:
     out=self._review_results_dir()
     (out/"process_steps.json").write_text(json.dumps(proc.steps,indent=2),encoding="utf-8")
    except Exception:pass
    self._review_ctx=None
   fig.canvas.mpl_connect("button_press_event",click);wb.set_close_handler(lambda:close(None));wb.refresh();wb.wait()
   if self._review_ctx is ctx:self._save_review_results(ctx);self._review_ctx=None
  except Exception as e:messagebox.showerror("Egg counting",str(e))
 def _save_overlays(self,out,im,automatic,review):
  base=Image.fromarray(gray8(im)).convert("RGB")
  def draw_points(path,table,accepted_filter=None):
   canvas=base.copy();draw=ImageDraw.Draw(canvas)
   if self.roi:
    pts=[tuple(map(float,p)) for p in self.roi];draw.line(pts+[pts[0]],fill=(0,255,255),width=2)
   if self.calibration_points and len(self.calibration_points)>1:
    draw.line(self.calibration_points,fill=(255,0,0),width=3)
   refs=self.reference_eggs or ([dict(points=self.reference_egg_points)] if self.reference_egg_points else [])
   for ref in refs:
    pts=[tuple(map(float,p)) for p in ref.get("points",[]) if p is not None]
    if len(pts)>1:draw.line(pts+[pts[0]],fill=(255,255,0),width=2)
   for _,row in table.iterrows():
    state=str(row.get("review_state","proposed" if accepted_filter is None else ("accepted" if bool(row.get("accepted",True)) else "rejected"))).lower()
    if state=="accepted":color=(0,255,0)
    elif state=="rejected":color=(255,0,0)
    elif state=="manual":color=(255,165,0)
    else:color=(0,255,255)
    x=float(row.x);y=float(row.y);r=7
    draw.ellipse((x-r,y-r,x+r,y+r),outline=color,width=2)
   canvas.save(out/path)
  draw_points("automatic_candidates_overlay.png",automatic)
  draw_points("reviewed_eggs_overlay.png",review,accepted_filter=True)
  draw_points("reviewed_eggs_all_states.png",review)
if __name__=="__main__":App().mainloop()
