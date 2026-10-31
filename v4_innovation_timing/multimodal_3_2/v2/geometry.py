"""Class-agnostic regions only INSIDE an FM9G-selected local image area.

Regions have geometry and numeric IDs, never object/color labels. FM9G must
recognize their original RGB crops before any region can initialize tracking.
"""
import cv2
import numpy as np


def local_regions(bgr,model_roi,max_regions=8):
    if model_roi is None:return [],[]
    height,width=bgr.shape[:2]
    x1,y1,x2,y2=map(int,model_roi)
    if not (0<=x1<x2<=width and 0<=y1<y2<=height):return [],[]
    if (x2-x1)*(y2-y1)>.75*width*height:return [],[]
    crop=bgr[y1:y2,x1:x2]
    graph=cv2.ximgproc.segmentation.createGraphSegmentation(sigma=.5,k=300,min_size=30)
    labels=graph.processImage(crop)
    candidates=[]
    for identifier in np.unique(labels):
        ys,xs=np.nonzero(labels==identifier)
        left,top,right,bottom=int(xs.min())+x1,int(ys.min())+y1,int(xs.max())+x1+1,int(ys.max())+y1+1
        if len(xs)<16 or right-left<4 or bottom-top<4:continue
        if ((left<=x1 and x1>0) or (top<=y1 and y1>0) or
                (right>=x2 and x2<width) or (bottom>=y2 and y2<height)):continue
        candidates.append(dict(region=int(identifier),bbox=[left,top,right,bottom],area=len(xs)))
    candidates.sort(key=lambda row:(-row['area'],row['region']))
    candidates=candidates[:max_regions]
    for row in candidates:
        left,top,right,bottom=row['bbox']
        patch=bgr[top:bottom,left:right].copy()
        region_mask=labels[top-y1:bottom-y1,left-x1:right-x1]==row['region']
        patch[~region_mask]=0
        row['_pixels_bgr']=patch
    retained={row['region'] for row in candidates}
    edges=set()
    for first,second in ((labels[:,:-1],labels[:,1:]),(labels[:-1,:],labels[1:,:])):
        different=first!=second
        pairs=np.unique(np.stack([first[different],second[different]],axis=1),axis=0)
        for a,b in pairs:
            a,b=int(a),int(b)
            if a in retained and b in retained:edges.add(tuple(sorted((a,b))))
    return candidates,[list(edge) for edge in sorted(edges)]


def model_selected_box(candidates,adjacency,labels,color):
    if len(candidates)!=len(labels):raise ValueError('Region-label count mismatch')
    selected={row['region']:row for row,label in zip(candidates,labels) if label==color}
    groups=[]
    pending=set(selected)
    while pending:
        seed=min(pending);pending.remove(seed);group={seed};todo=[seed]
        while todo:
            identifier=todo.pop()
            neighbors={b if a==identifier else a for a,b in adjacency if identifier in (a,b)}
            added=neighbors&pending;pending-=added;group|=added;todo.extend(sorted(added))
        groups.append(group)
    if not groups:return None
    group=min(groups,key=lambda g:(-sum(selected[i]['area'] for i in g),min(g)))
    boxes=[selected[i]['bbox'] for i in group]
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),
            max(b[2] for b in boxes),max(b[3] for b in boxes)]
