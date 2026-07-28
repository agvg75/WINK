from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import cv2
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/"movie"));sys.path.insert(0,str(HERE.parent/"pharynx_morphometry"));sys.path.insert(0,str(HERE.parents[1]/"app"))
from movie_reader import open_movie
from orientation_defaults import load_defaults,save_defaults,image_orientation
from nonstriated_morphology import analyze,gray8,segment_strands,strand_vectors
from process_ui import CockpitApp

class App(CockpitApp):
 def __init__(self):
  super().__init__("Nonstriated Muscle Morphology",geometry="1180x760",process_title="Myocyte morphometry")
  d=load_defaults();self.roi=None;self.muscle_rois={};self.vector=None;self.scale=None;self.image=None;self.preview_fig=None;self.preview_axes=None;self._preview_job=None
  self.source=tk.StringVar();self.frame=tk.StringVar(value="0");self.mode=tk.StringVar(value="anal_depressor");self.known=tk.StringVar(value="50");self.ap=tk.StringVar(value=d["anterior_posterior"]);self.dv=tk.StringVar(value=d["dorsal_ventral"]);self.status=tk.StringVar(value="Choose a raw image, stack, movie, or image folder.")
  self.ridge_pct=tk.DoubleVar(value=82);self.ridge_sigma=tk.IntVar(value=5);self.min_obj=tk.IntVar(value=18);self.min_vector=tk.IntVar(value=20)
  self._build_controls();self._build_center()
  self.status.trace_add("write",lambda *_:self.set_status(self.status.get()));self.set_status(self.status.get())
 def _build_controls(self):
  c=self.controls
  def field_entry(label,var):
   row=ttk.Frame(c);row.pack(fill="x",pady=3);ttk.Label(row,text=label,width=20).pack(side="left");e=ttk.Entry(row,textvariable=var);e.pack(side="right",fill="x",expand=True);return e
  def field_combo(label,var,values):
   row=ttk.Frame(c);row.pack(fill="x",pady=3);ttk.Label(row,text=label,width=20).pack(side="left");cb=ttk.Combobox(row,textvariable=var,values=values,state="readonly");cb.pack(side="right",fill="x",expand=True);return cb
  src=ttk.Frame(c);src.pack(fill="x",pady=3);ttk.Label(src,text="Source",width=20).pack(side="left");ttk.Entry(src,textvariable=self.source).pack(side="left",fill="x",expand=True);ttk.Button(src,text="Choose",width=7,command=self._choose_and_show).pack(side="right")
  fe=field_entry("Frame",self.frame);fe.bind("<Return>",lambda _e:self._show_frame())
  ttk.Button(c,text="Show / refresh frame",command=self._show_frame).pack(fill="x",pady=(0,4))
  field_combo("Tissue mode",self.mode,["pharynx","uterine","somatointestinal","anal_depressor"])
  field_entry("Calibration distance (um)",self.known)
  field_combo("Anterior to posterior",self.ap,["left_to_right","right_to_left"])
  field_combo("Dorsal direction",self.dv,["dorsal_up","dorsal_down"])
  ttk.Button(c,text="Save directions as defaults",command=self.save).pack(fill="x",pady=(8,2))
  ttk.Button(c,text="1. Calibrate (2-point on image)",command=self.calibrate).pack(fill="x",pady=2)
  self.add_scale_button(self._current_frame,self._apply_scale,initial=lambda:self.scale,text="Calibrate scale (scope / bar)...").pack(fill="x",pady=2)
  ttk.Button(c,text="2. Draw tissue ROI / 4 uterine territories",command=self.draw).pack(fill="x",pady=2)
  ttk.Button(c,text="Mark A->I vector (anal depressor)",command=self.mark_vector).pack(fill="x",pady=2)
  opts=ttk.LabelFrame(c,text="Uterine strand detection (least to more inclusive)");opts.pack(fill="x",pady=8)
  for lab,var,lo,hi in [("Ridge threshold percentile",self.ridge_pct,50,99),("Maximum strand half-width (px)",self.ridge_sigma,2,12),("Minimum detected object (px)",self.min_obj,2,200),("Minimum vector length (px)",self.min_vector,3,100)]:
   row=ttk.Frame(opts);row.pack(fill="x",pady=2);ttk.Label(row,text=lab,wraplength=150,justify="left").pack(side="left");ttk.Label(row,textvariable=var,width=5).pack(side="right");ttk.Scale(row,variable=var,from_=lo,to=hi,orient="horizontal",command=lambda _v:self._schedule_preview_refresh()).pack(side="right",fill="x",expand=True)
  ttk.Button(c,text="3. Preview mask + vectors",command=self.preview).pack(fill="x",pady=(8,2))
  ttk.Button(c,text="4. Analyze and save",command=self.run).pack(fill="x",pady=2)
 def _build_center(self):
  ttk.Label(self.center,text="Myocyte / nonstriated muscle morphometry",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=6,pady=(6,2))
  ttk.Label(self.center,textvariable=self.status,wraplength=560,justify="left",foreground="#444444").pack(anchor="w",padx=6,pady=(0,4))
  self.center_fig=Figure(figsize=(6.0,5.0),dpi=100);self.center_ax=self.center_fig.add_subplot(111);self.center_ax.set_axis_off()
  self.center_canvas=FigureCanvasTkAgg(self.center_fig,master=self.center);self.center_canvas.get_tk_widget().pack(fill="both",expand=True,padx=6,pady=6)
  self.center_ax.text(0.5,0.5,"Choose a source image; the selected frame appears here.",ha="center",va="center",fontsize=10,color="#888888");self.center_canvas.draw()
 def _choose_and_show(self):
  path=filedialog.askopenfilename()
  if path:
   self.source.set(path);self._show_frame()
 def _show_frame(self):
  if not self.source.get().strip():
   self.status.set("Choose a source image first.");return
  try:
   im=self.load()
  except Exception as exc:
   self.status.set(f"Could not load that frame: {exc}");return
  self._preview_active=False
  self.center_fig.clear();self.center_ax=self.center_fig.add_subplot(111);self.center_ax.set_axis_off()
  self.center_ax.imshow(im,cmap="gray");self.center_ax.set_title(f"Frame {self.frame.get()}",fontsize=9);self.center_canvas.draw()
  self.status.set("Frame loaded. Calibrate the scale, draw the ROI, preview, then Analyze and save.")
 def _current_frame(self):
  try:return self.load()
  except Exception:return None
 def _apply_scale(self,res):
  self.scale=float(res["um_per_px"]);self.status.set(f"Scale set: {self.scale:.4f} um/pixel ({res.get('details','')})");self.log("Scale calibrated",f"{self.scale:.4f} um/px",status="edit")
 def load(self):m=open_movie(self.source.get());self.image=m.get_frame(int(self.frame.get()));m.close();return gray8(self.image)
 def save(self):save_defaults(self.ap.get(),self.dv.get());self.status.set("Orientation defaults saved for future images.")
 def calibrate(self):
  self._show_frame()
  if self.image is None:
   self.status.set("Choose and show a source image first.");return
  self._calib_pts=[]
  self._calib_cid=self.center_canvas.mpl_connect("button_press_event",self._calib_click)
  self.status.set("Calibration: click the two ends of a known distance directly on the image below. Right-click to cancel.")
 def _calib_click(self,event):
  if getattr(self,"_calib_cid",None) is None:return
  if event.button==3:
   self._calib_end();self.status.set("Calibration canceled; the previous scale was kept.");return
  if event.inaxes!=self.center_ax or event.xdata is None:return
  self._calib_pts.append((float(event.xdata),float(event.ydata)))
  self.center_ax.plot(event.xdata,event.ydata,"+",color="#00e0ff",ms=13,mew=2);self.center_canvas.draw_idle()
  if len(self._calib_pts)>=2:
   (x0,y0),(x1,y1)=self._calib_pts[:2];pixels=float(np.hypot(x1-x0,y1-y0));self._calib_end()
   if pixels<1:
    self.status.set("The two points are too close together; click 1. Calibrate and try again.");return
   try:known=float(self.known.get())
   except (TypeError,ValueError):self.status.set("Calibration distance (um) must be a number.");return
   self.scale=known/pixels;self.status.set(f"Calibration accepted: {pixels:.1f} px = {known:g} um; scale {self.scale:.4f} um/pixel");self.log("Scale calibrated",f"{self.scale:.4f} um/px (2-point, {pixels:.1f} px)",status="edit")
 def _calib_end(self):
  cid=getattr(self,"_calib_cid",None)
  if cid is not None:
   try:self.center_canvas.mpl_disconnect(cid)
   except Exception:pass
  self._calib_cid=None
 def draw(self):
  self._show_frame()
  if self.image is None:
   self.status.set("Choose and show a source image first.");return
  self._roi_verts=[];self._roi_artists=[]
  if self.mode.get()=="uterine":
   self._roi_labels=["anterior_um1","anterior_um2","posterior_um1","posterior_um2"];self._roi_collected={}
  else:
   self._roi_labels=None;self._roi_collected=None
  self._roi_cid=self.center_canvas.mpl_connect("button_press_event",self._roi_click)
  self._roi_prompt()
 def _roi_prompt(self):
  if self._roi_labels is not None:
   i=len(self._roi_collected);name=self._roi_labels[i].replace("_"," ")
   self.status.set(f"Uterine territory {i+1}/4: {name}. Left-click the vertices, right-click to close the polygon (draw the EXPECTED territory even if no signal is visible).")
  else:
   self.status.set("Draw the tissue ROI: left-click vertices around the muscle on the image, right-click to close (needs 3+ vertices).")
 def _roi_click(self,event):
  if getattr(self,"_roi_cid",None) is None:return
  if event.button==3:
   self._roi_finish();return
  if event.inaxes!=self.center_ax or event.xdata is None:return
  self._roi_verts.append((float(event.xdata),float(event.ydata)))
  a,=self.center_ax.plot(event.xdata,event.ydata,"o",color="#ffcc00",ms=4);self._roi_artists.append(a)
  if len(self._roi_verts)>=2:
   xs=[p[0] for p in self._roi_verts];ys=[p[1] for p in self._roi_verts];ln,=self.center_ax.plot(xs,ys,"-",color="#ffcc00",lw=1);self._roi_artists.append(ln)
  self.center_canvas.draw_idle()
 def _roi_finish(self):
  if len(self._roi_verts)<3:
   self.status.set("Need at least 3 vertices; keep left-clicking, then right-click to close.");return
  poly=list(self._roi_verts);xs=[p[0] for p in poly]+[poly[0][0]];ys=[p[1] for p in poly]+[poly[0][1]]
  ln,=self.center_ax.plot(xs,ys,"-",color="#00ff66",lw=1.6);self._roi_artists.append(ln);self.center_canvas.draw_idle()
  if self._roi_labels is not None:
   self._roi_collected[self._roi_labels[len(self._roi_collected)]]=poly;self._roi_verts=[]
   if len(self._roi_collected)<4:
    self._roi_prompt();return
   self._roi_end();mask=np.zeros(self.image.shape[:2],np.uint8)
   for pts in self._roi_collected.values():cv2.fillPoly(mask,[np.round(pts).astype(np.int32)],1)
   self.roi=mask;self.muscle_rois=dict(self._roi_collected)
   self.status.set("Four uterine territories accepted. Preview next.");self.log("ROI drawn","4 uterine territories",status="edit")
  else:
   self._roi_end();self.roi=poly;self.muscle_rois={}
   self.status.set(f"Tissue ROI accepted ({len(poly)} vertices). Preview next.");self.log("ROI drawn",f"{len(poly)}-vertex tissue ROI",status="edit")
 def _roi_end(self):
  cid=getattr(self,"_roi_cid",None)
  if cid is not None:
   try:self.center_canvas.mpl_disconnect(cid)
   except Exception:pass
  self._roi_cid=None;self._roi_verts=[]
 def mark_vector(self):
  self._show_frame()
  if self.image is None:
   self.status.set("Choose and show a source image first.");return
  self._vec_pts=[];self._vec_cid=self.center_canvas.mpl_connect("button_press_event",self._vec_click)
  self.status.set("Anal depressor: click the proximal attachment, then the distal insertion, on the image. Right-click to cancel.")
 def _vec_click(self,event):
  if getattr(self,"_vec_cid",None) is None:return
  if event.button==3:
   self._vec_end();self.status.set("Vector marking canceled.");return
  if event.inaxes!=self.center_ax or event.xdata is None:return
  self._vec_pts.append((float(event.xdata),float(event.ydata)))
  self.center_ax.plot(event.xdata,event.ydata,"o",color="#ff4fd8",ms=6);self.center_canvas.draw_idle()
  if len(self._vec_pts)>=2:
   (x0,y0),(x1,y1)=self._vec_pts[:2];self.center_ax.annotate("",xy=(x1,y1),xytext=(x0,y0),arrowprops=dict(arrowstyle="->",color="#ff4fd8",lw=2));self.center_canvas.draw_idle()
   self.vector=[self._vec_pts[0],self._vec_pts[1]];self._vec_end();self.status.set("Attachment-to-insertion vector marked. Analyze and save.");self.log("Vector marked","anal depressor proximal->distal",status="edit")
 def _vec_end(self):
  cid=getattr(self,"_vec_cid",None)
  if cid is not None:
   try:self.center_canvas.mpl_disconnect(cid)
   except Exception:pass
  self._vec_cid=None
 def preview(self):
  if self.roi is None:
   self.status.set("Draw the tissue ROI first.");return
  try:
   if self.image is None:self.load()
   im,seg,response,thr=segment_strands(self.image,self.roi,self.ridge_pct.get(),self.min_obj.get(),self.ridge_sigma.get());sk,vectors=strand_vectors(seg,self.min_vector.get())
  except Exception as e:
   self.status.set(f"Preview failed: {e}");return
  self.center_fig.clear();a=self.center_fig.add_subplot(1,2,1);b=self.center_fig.add_subplot(1,2,2)
  a.imshow(im,cmap="gray");a.set_title("Raw + territories",fontsize=8)
  if self.muscle_rois:
   colors=["cyan","magenta","orange","deepskyblue"]
   for (label,points),color in zip(self.muscle_rois.items(),colors):
    poly=np.asarray(points);a.plot(np.r_[poly[:,0],poly[0,0]],np.r_[poly[:,1],poly[0,1]],color=color,lw=1)
  elif isinstance(self.roi,(list,tuple)):
   poly=np.asarray(self.roi);a.plot(np.r_[poly[:,0],poly[0,0]],np.r_[poly[:,1],poly[0,1]],"c-")
  b.imshow(im,cmap="gray");b.imshow(np.ma.masked_where(~seg,seg),cmap="Greens",alpha=.38);b.imshow(np.ma.masked_where(~sk,sk),cmap="autumn",alpha=.9)
  for v in vectors:b.annotate("",xy=(v["x1"],v["y1"]),xytext=(v["x0"],v["y0"]),arrowprops=dict(arrowstyle="->",color="yellow",lw=.8))
  b.set_title(f"Mask + skeleton + {len(vectors)} vectors",fontsize=8)
  for x in (a,b):x.set_axis_off()
  try:self.center_fig.tight_layout()
  except Exception:pass
  self.center_ax=b;self._preview_active=True;self.center_canvas.draw()
  self.status.set(f"Preview: {int(seg.sum())} px, {len(vectors)} vectors. Move the sliders to refresh, then Analyze and save.")
 def _schedule_preview_refresh(self):
  if not getattr(self,"_preview_active",False) or self.roi is None:return
  if self._preview_job is not None:
   try:self.after_cancel(self._preview_job)
   except Exception:pass
  self._preview_job=self.after(250,self.preview)
 def run(self):
  try:
   if self.mode.get()=="pharynx":
    from pharynx_tool import App as PharynxTemplateApp
    messagebox.showinfo("Pharyngeal mode","Opening the anchored four-compartment pharynx template. The generic nonstriated feature definitions are not applied.")
    PharynxTemplateApp().mainloop();return
   if not self.scale or self.roi is None:raise ValueError("Calibrate and draw the tissue ROI first")
   if self.mode.get()!="anal_depressor":self.vector=None
   if self.mode.get()=="anal_depressor" and not self.vector:
    raise ValueError("Anal depressor mode: click 'Mark A->I vector' and set the proximal-to-distal vector on the image first.")
   if self.mode.get()=="uterine" and len(self.muscle_rois)!=4:raise ValueError("Uterine analysis requires all four expected muscle territories")
   defaults=load_defaults();orient=image_orientation(defaults,self.ap.get(),self.dv.get());rec,out=analyze(self.image,self.mode.get(),self.scale,self.roi,orient,self.vector,Path(self.source.get()).parent/(Path(self.source.get()).stem+"_morphology"),Path(self.source.get()).stem,self.ridge_pct.get(),self.min_obj.get(),self.ridge_sigma.get(),self.min_vector.get(),self.muscle_rois)
   self.status.set(f"Features and vectors saved: {out}");messagebox.showinfo("Complete",f"Mask, skeleton, strand vectors, and transparent features saved.\nQC: {rec['segmentation_qc']}\nNo unvalidated composite score was assigned.\n{out}")
  except Exception as e:messagebox.showerror("Morphology",str(e))
if __name__=="__main__":App().mainloop()
