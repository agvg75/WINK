"""Small-cache, array-like access to movies without materializing T×H×W."""
from __future__ import annotations
from collections import OrderedDict
import numpy as np
import tempfile
import atexit
from pathlib import Path


class VirtualFrameStack:
    is_virtual_stack = True

    def __init__(self, movie, crop=None, channel="gray", cache_frames=4):
        self.movie=movie;self.channel=channel;self.cache_frames=max(1,int(cache_frames))
        h,w=int(movie.height),int(movie.width)
        self.crop=tuple(crop or (0,0,w,h));x0,y0,x1,y1=self.crop
        self.shape=(int(movie.n_frames),int(y1-y0),int(x1-x0))
        self.ndim=3;self.dtype=np.dtype(np.float32);self._cache=OrderedDict()

    def __len__(self):return self.shape[0]

    def _decode(self,index):
        index=int(index)
        if index<0:index+=self.shape[0]
        if index in self._cache:
            frame=self._cache.pop(index);self._cache[index]=frame;return frame
        source=np.asarray(self.movie.get_frame(index));x0,y0,x1,y1=self.crop
        source=source[y0:y1,x0:x1]
        if source.ndim==3:
            if self.channel=="green" and source.shape[2]>=3:
                frame=source[...,1]
            else:
                frame=np.add.reduce(source[...,:3],axis=2,dtype=np.float32)/np.float32(3)
        else:frame=source
        frame=np.asarray(frame)
        self._cache[index]=frame
        while len(self._cache)>self.cache_frames:self._cache.popitem(last=False)
        return frame

    def __getitem__(self,key):
        if isinstance(key,tuple):return self._decode(key[0])[key[1:]]
        if isinstance(key,(int,np.integer)):return self._decode(key)
        indices=np.arange(self.shape[0])[key]
        return np.stack([self._decode(i) for i in np.atleast_1d(indices)])

    def close(self):
        self._cache.clear();self.movie.close()


class DiskBackedFrameStack:
    """Numpy-compatible temporary stack stored on disk rather than in RAM."""
    is_virtual_stack=True

    @classmethod
    def from_movie(cls,movie,crop=None,channel="gray",source_indices=None,progress_callback=None):
        h,w=int(movie.height),int(movie.width);crop=tuple(crop or (0,0,w,h))
        x0,y0,x1,y1=crop;iterator=iter(movie.frames());first=np.asarray(next(iterator))
        dtype=np.uint8 if first.dtype.itemsize<=1 else np.uint16 if first.dtype.itemsize<=2 else np.float32
        handle=tempfile.NamedTemporaryFile(prefix="nike_virtual_stack_",suffix=".npy",delete=False);path=Path(handle.name);handle.close()
        wanted=(list(range(int(movie.n_frames))) if source_indices is None else sorted(set(int(i) for i in source_indices)))
        wanted_set=set(wanted);data=np.lib.format.open_memmap(path,mode="w+",dtype=dtype,shape=(len(wanted),y1-y0,x1-x0))
        def convert(source):
            source=np.asarray(source)[y0:y1,x0:x1]
            if source.ndim==3:
                if channel=="green" and source.shape[2]>=3:source=source[...,1]
                else:source=np.add.reduce(source[...,:3],axis=2,dtype=np.float32)/3.0
            return np.asarray(np.clip(source,0,np.iinfo(dtype).max) if np.issubdtype(dtype,np.integer) else source,dtype=dtype)
        written=0
        if 0 in wanted_set:data[written]=convert(first);written+=1
        for index,frame in enumerate(iterator,start=1):
            if index in wanted_set:data[written]=convert(frame);written+=1
            if progress_callback and (index%3==0 or index+1>=int(movie.n_frames)):progress_callback(index+1,int(movie.n_frames),"Decoding selected frames")
            if written>=len(wanted):break
        if written<data.shape[0]:data=data[:written]
        data.flush();movie.close();obj=cls(path,data,crop);obj.source_indices=np.asarray(wanted[:written],dtype=int);return obj

    def __init__(self,path,data,crop):
        self.path=Path(path);self.data=data;self.crop=tuple(crop)
        self.shape=data.shape;self.ndim=3;self.dtype=data.dtype
        atexit.register(self._cleanup_path)

    def __len__(self):return self.shape[0]
    def __getitem__(self,key):return self.data[key]
    def close(self):
        mmap=getattr(self.data,"_mmap",None)
        if mmap is not None:mmap.close()
        self.data=None
        self._cleanup_path()

    def _cleanup_path(self):
        try:self.path.unlink()
        except OSError:pass
