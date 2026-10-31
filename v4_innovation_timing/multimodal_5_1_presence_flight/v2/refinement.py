"""Class-agnostic foreground refinement AFTER an FM9G target is selected.

No color/class scores or whole-image proposals are produced. A missing model
box always stays missing. This is only the geometric initialization of a tracker.
"""
import cv2
import numpy as np


def refine(bgr, model_box, audit=lambda **kwargs:None, _context=False):
    if model_box is None:
        return None
    height,width=bgr.shape[:2]
    x1,y1,x2,y2=[int(round(v)) for v in model_box]
    if not (0<=x1<x2<=width and 0<=y1<y2<=height):
        return None
    margin_x=max(64,round((x2-x1)*0.5))
    margin_y=max(64,round((y2-y1)*0.5))
    rx1,ry1=max(0,x1-margin_x),max(0,y1-margin_y)
    rx2,ry2=min(width,x2+margin_x),min(height,y2+margin_y)
    # Local pixels only. No labels, hue cutoffs, balloon dimensions, positions,
    # or pretrained detector are used to build this appearance segmentation.
    crop=bgr[ry1:ry2,rx1:rx2].copy()
    ch,cw=crop.shape[:2]
    mask=np.full((ch,cw),cv2.GC_BGD,dtype=np.uint8)
    # Coarse semantic-window intersections can cut through the true object.
    # Retry only a rejected initialization with local uncertainty, keeping the
    # original model box as probable foreground and added pixels probable BG.
    uncertainty_x=max(8,round((x2-x1)*.25)) if _context else 8
    uncertainty_y=max(8,round((y2-y1)*.25)) if _context else 8
    sx1,sy1=max(0,x1-rx1-uncertainty_x),max(0,y1-ry1-uncertainty_y)
    sx2,sy2=min(cw,x2-rx1+uncertainty_x),min(ch,y2-ry1+uncertainty_y)
    mask[sy1:sy2,sx1:sx2]=cv2.GC_PR_BGD
    mask[max(0,y1-ry1):min(ch,y2-ry1),max(0,x1-rx1):min(cw,x2-rx1)]=cv2.GC_PR_FGD
    mask[:2,:]=mask[-2:,:]=mask[:,:2]=mask[:,-2:]=cv2.GC_BGD
    # Anchor is the model's own initial box, never a color-based seed.
    ax,ay=(x1+x2)//2-rx1,(y1+y2)//2-ry1
    if 2<=ax<cw-2 and 2<=ay<ch-2:
        mask[ay-1:ay+2,ax-1:ax+2]=cv2.GC_FGD
    background=np.zeros((1,65),np.float64)
    foreground=np.zeros((1,65),np.float64)
    cv2.setRNGSeed(0)
    cv2.grabCut(crop,mask,None,background,foreground,4,cv2.GC_INIT_WITH_MASK)
    binary=np.uint8((mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD))
    kernel=max(7,min(51,int(round(min(x2-x1,y2-y1)/6))|1))
    binary=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((kernel,kernel),np.uint8))
    count,labels,stats,centers=cv2.connectedComponentsWithStats(binary,connectivity=8)
    candidates=[]
    for index in range(1,count):
        x,y,w,h,area=stats[index]
        if area<16 or w<4 or h<4: continue
        # Reject background leaking to the artificial ROI border. A genuine
        # image-edge target is treated separately by the model as partial.
        if x<=sx1 or y<=sy1 or x+w>=sx2 or y+h>=sy2: continue
        # A real image-edge fragment is permitted only after the runtime asks
        # FM9G to verify this foreground crop again. It remains a partial box.
        distance=(centers[index][0]-ax)**2+(centers[index][1]-ay)**2
        candidates.append((distance,[int(x+rx1),int(y+ry1),int(x+w+rx1),int(y+h+ry1)]))
    chosen=min(candidates,key=lambda item:item[0])[1] if candidates else None
    audit(kind='foreground_refinement',context_fraction=.25 if _context else 0.,
          allowed_roi=[sx1+rx1,sy1+ry1,sx2+rx1,sy2+ry1],bbox=chosen)
    if chosen is None and not _context:
        return refine(bgr,model_box,audit,_context=True)
    return chosen
