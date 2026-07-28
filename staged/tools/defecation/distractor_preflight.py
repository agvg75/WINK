"""Preflight scrubber for moving non-target worm annotations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

SCHEMA_VERSION = "1.0"


def save_annotations(path, source, frame_count, episodes):
    document = {
        "schema_version": SCHEMA_VERSION, "source": str(Path(source).resolve()),
        "frame_count": int(frame_count), "episodes": episodes,
        "meaning": (
            "Each episode is one moving distractor worm from its first clear "
            "annotation through its last visible frame; not a static exclusion ROI."),
    }
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, allow_nan=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def load_annotations(path):
    path = Path(path)
    if not path.is_file(): return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if str(data.get("schema_version")) != SCHEMA_VERSION:
        raise ValueError("Unsupported distractor annotation schema.")
    return list(data.get("episodes", []))


class DistractorPreflight(tk.Toplevel):
    def __init__(self, parent, paths, save_path):
        super().__init__(parent)
        self.title("WINK moving-distractor preflight")
        self.geometry("1050x760"); self.minsize(850, 620)
        self.paths = list(paths); self.save_path = Path(save_path)
        self.episodes = load_annotations(save_path)
        self.frame = 0; self.photo = None; self.accepted = False
        self._setting = False
        self._build(); self._show(0)
        self.bind("<Left>", lambda e:self._show(self.frame-(10 if e.state&1 else 1)))
        self.bind("<Right>", lambda e:self._show(self.frame+(10 if e.state&1 else 1)))

    def _build(self):
        ttk.Label(self, text="Identify every moving non-target worm",
                  font=("Segoe UI",15,"bold")).pack(anchor="w",padx=10,pady=(8,2))
        ttk.Label(self, text=(
            "Scrub to the first clear frame of a distractor, draw a segmented "
            "line from one end to the other, and declare its last visible frame. "
            "Do not annotate the target. Overlaps will be refused, not guessed."),
            wraplength=1000).pack(anchor="w",padx=10)
        body=ttk.Panedwindow(self,orient="horizontal");body.pack(fill="both",expand=True,padx=10,pady=6)
        left=ttk.Frame(body);right=ttk.Frame(body,width=300);body.add(left,weight=4);body.add(right,weight=1)
        self.image=ttk.Label(left,anchor="center");self.image.pack(fill="both",expand=True)
        self.info=ttk.Label(left);self.info.pack(fill="x")
        self.slider=tk.Scale(left,from_=0,to=max(0,len(self.paths)-1),orient="horizontal",showvalue=False,command=self._slide)
        self.slider.pack(fill="x")
        self.listbox=tk.Listbox(right,font=("Consolas",9));self.listbox.pack(fill="both",expand=True)
        ttk.Button(right,text="Add moving distractor at this frame",command=self._add).pack(fill="x",pady=3)
        ttk.Button(right,text="Delete selected episode",command=self._delete).pack(fill="x",pady=3)
        ttk.Button(right,text="Save and use these distractors",command=self._finish).pack(fill="x",pady=(14,3))
        ttk.Button(right,text="No distractors / clear all",command=self._clear).pack(fill="x",pady=3)
        self._refresh()

    def _slide(self,value):
        if not self._setting:self._show(int(float(value)),False)

    def _show(self,frame,set_slider=True):
        self.frame=max(0,min(len(self.paths)-1,int(frame)))
        if set_slider:
            self._setting=True
            try:self.slider.set(self.frame)
            finally:self._setting=False
        array=cv2.imread(str(self.paths[self.frame]),cv2.IMREAD_GRAYSCALE)
        lo,hi=np.percentile(array,(.5,99.5));shown=np.uint8(np.clip((array-lo)*255/max(hi-lo,1),0,255))
        rgb=cv2.cvtColor(shown,cv2.COLOR_GRAY2RGB)
        for episode in self.episodes:
            if episode["start_frame"]<=self.frame<=episode["end_frame"]:
                pts=np.rint(episode["seed_centerline_xy"]).astype(np.int32)
                if self.frame==episode["seed_frame"]:cv2.polylines(rgb,[pts],False,(255,0,255),3)
        picture=Image.fromarray(rgb);picture.thumbnail((760,570),Image.Resampling.LANCZOS);self.photo=ImageTk.PhotoImage(picture);self.image.configure(image=self.photo)
        self.info.configure(text=f"Frame {self.frame}/{len(self.paths)-1}. Magenta lines appear on their seed frame.")

    def _add(self):
        import matplotlib.pyplot as plt
        array=cv2.imread(str(self.paths[self.frame]),cv2.IMREAD_GRAYSCALE)
        fig,ax=plt.subplots(figsize=(10,7));ax.imshow(array,cmap="gray");ax.set_title("Click a segmented line along the DISTRACTOR worm; Enter finishes")
        points=plt.ginput(-1,timeout=0);plt.close(fig)
        if len(points)<2:return
        end=simpledialog.askinteger("Last visible frame","Last frame on which this distractor is visible:",initialvalue=len(self.paths)-1,minvalue=self.frame,maxvalue=len(self.paths)-1,parent=self)
        if end is None:return
        label=simpledialog.askstring("Distractor label","Short label for this worm/entry episode:",initialvalue=f"distractor_{len(self.episodes)+1}",parent=self)
        if not label:return
        label = label.strip()
        if not label:return
        existing = {item["episode_id"] for item in self.episodes}
        if label in existing:
            messagebox.showerror(
                "Duplicate distractor label",
                "Each moving episode needs a unique label. Use a new label, "
                "including when the same worm leaves and later re-enters.",
                parent=self)
            return
        self.episodes.append({"episode_id":label,"seed_frame":self.frame,"start_frame":self.frame,"end_frame":int(end),"seed_centerline_xy":[[float(x),float(y)] for x,y in points]})
        self._refresh();self._show(self.frame)

    def _refresh(self):
        self.listbox.delete(0,"end")
        for item in self.episodes:self.listbox.insert("end",f"{item['episode_id']}: {item['start_frame']}-{item['end_frame']} seed {item['seed_frame']}")

    def _delete(self):
        selected=self.listbox.curselection()
        if selected:self.episodes.pop(selected[0]);self._refresh();self._show(self.frame)

    def _clear(self):
        if messagebox.askyesno("Clear distractors","Remove all distractor episodes?",parent=self):self.episodes=[];self._refresh();self._show(self.frame)

    def _finish(self):
        save_annotations(self.save_path,self.paths[0].parent,len(self.paths),self.episodes)
        self.accepted=True;self.destroy()
