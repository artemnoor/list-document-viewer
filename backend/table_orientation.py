"""Bounded orientation search with inverse mapping to the original page."""
import math
import numpy as np
import cv2
from types import SimpleNamespace
from PIL import Image


def rotate_image(image, angle):
    w,h=image.size;matrix=cv2.getRotationMatrix2D((w/2,h/2),angle,1)
    c,s=abs(matrix[0,0]),abs(matrix[0,1]);nw,nh=math.ceil(h*s+w*c),math.ceil(h*c+w*s)
    matrix[0,2]+=nw/2-w/2;matrix[1,2]+=nh/2-h/2
    return Image.fromarray(cv2.warpAffine(np.asarray(image),matrix,(nw,nh),borderValue=(255,255,255))),matrix


def skew_angle(image):
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    lines=cv2.HoughLinesP(cv2.Canny(gray,60,180),1,np.pi/1800,90,minLineLength=min(image.size)*.18,maxLineGap=15)
    if lines is None:return 0.
    angles=[]
    for x1,y1,x2,y2 in lines[:,0]:
        a=math.degrees(math.atan2(y2-y1,x2-x1));a=(a+45)%90-45
        angles.append(a)
    return float(np.median(angles)) if angles else 0.


def orient_table(image, page_size, page_no, ai_budget=None, warnings=None):
    from ocr_layout import _detail_reader,_raster_tables,recover_empty_cells,recover_empty_headers,retry_empty_numeric_cells, _grid_ink
    original_size=image.size
    perspective=np.eye(3);rectified=False
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    binary=_grid_ink(image)
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:3]:
        if cv2.contourArea(contour)<image.width*image.height*.1:continue
        poly=cv2.approxPolyDP(contour,.015*cv2.arcLength(contour,True),True)
        if len(poly)!=4:continue
        pts=poly[:,0].astype(np.float32);s=pts.sum(axis=1);diff=np.diff(pts,axis=1).ravel()
        points=np.array([pts[s.argmin()],pts[diff.argmin()],pts[s.argmax()],pts[diff.argmax()]],dtype=np.float32)
        edges=[points[(i+1)%4]-points[i] for i in range(4)]
        def parallel(a,b):return abs(float(a[0]*b[1]-a[1]*b[0]))/max(1,float(np.linalg.norm(a)*np.linalg.norm(b)))<.01
        if parallel(edges[0],edges[2]) and parallel(edges[1],edges[3]):break
        left,top=points.min(axis=0);right,bottom=points.max(axis=0)
        target=np.float32([[left,top],[right,top],[right,bottom],[left,bottom]])
        if np.max(abs(points-target))<4:break
        perspective=cv2.getPerspectiveTransform(points,target)
        image=Image.fromarray(cv2.warpPerspective(np.asarray(image),perspective,image.size,borderValue=(255,255,255)));rectified=True;break
    skew=skew_angle(image);choices=[]
    for turn in (0,90,180,270):
        angle=turn+skew
        corrected,matrix=rotate_image(image,angle)
        output=_detail_reader()(np.asarray(corrected),use_det=True,use_cls=False,use_rec=True)
        parts=[];scores=[]
        if output.txts is not None:
            for text,score,box in zip(output.txts,output.scores,output.boxes):
                if not text.strip():continue
                xs=[float(p[0]) for p in box];ys=[float(p[1]) for p in box]
                parts.append({'kind':'text','text':text,'source':'ocr_oriented','confidence':float(score),'provenance':[{'page_no':page_no,'bbox':{'l':min(xs),'t':min(ys),'r':max(xs),'b':max(ys),'coord_origin':'TOPLEFT'}}]})
                scores.append((float(score),len(text)))
        tables=_raster_tables(corrected,SimpleNamespace(width=corrected.width,height=corrected.height),parts,page_no)
        quality=sum(s*n for s,n in scores)/max(1,sum(n for s,n in scores))
        horizontal=sum(1 for p in parts if (p['provenance'][0]['bbox']['r']-p['provenance'][0]['bbox']['l']) > (p['provenance'][0]['bbox']['b']-p['provenance'][0]['bbox']['t'])*1.5)
        quality+=.35*horizontal/max(1,len(parts)) + min(len(parts),40)*.002
        if tables:
            quality+=.2
        choices.append((quality,turn,angle,parts,tables,matrix))
        corrected.close()
    best=max(choices,key=lambda c:c[0]);_,turn,angle,parts,tables,matrix=best
    if not tables or (turn==0 and abs(skew)<.4 and not rectified):return None
    from table_text import normalize_table_text
    tables=[normalize_table_text(table) for table in tables]
    corrected,_=rotate_image(image,angle)
    try:
        from ocr_layout import retry_text_cells
        retry_text_cells(corrected, SimpleNamespace(width=corrected.width,height=corrected.height), tables, parts)
        recover_empty_cells(corrected,SimpleNamespace(width=corrected.width,height=corrected.height),tables,parts)
        retry_empty_numeric_cells(corrected,SimpleNamespace(width=corrected.width,height=corrected.height),tables)
        if ai_budget is not None:
            from polza_fallback import recover_cells
            notices = recover_cells(corrected,SimpleNamespace(width=corrected.width,height=corrected.height),tables,ai_budget)
            if warnings is not None: warnings.extend(notices)
        recover_empty_headers(corrected,SimpleNamespace(width=corrected.width,height=corrected.height),tables)
    finally:corrected.close()
    selected=[]
    for part in parts:
        b=part['provenance'][0]['bbox'];cx=(b['l']+b['r'])/2;cy=(b['t']+b['b'])/2
        if not any(t['provenance'][0]['bbox']['l']<=cx<=t['provenance'][0]['bbox']['r'] and t['provenance'][0]['bbox']['t']<=cy<=t['provenance'][0]['bbox']['b'] for t in tables):selected.append(part)
    selected.extend(tables)
    homogeneous=np.vstack([matrix,[0,0,1]])@perspective
    inverse=np.linalg.inv(homogeneous);sx,sy=page_size.width/original_size[0],page_size.height/original_size[1]
    def unmap(box):
        l,t,r,b=box;points=np.array([[l,t,1],[r,t,1],[r,b,1],[l,b,1]])@inverse.T
        points=points[:,:2]/points[:,2:3]
        return [max(0,float(points[:,0].min())*sx),max(0,float(points[:,1].min())*sy),min(page_size.width,float(points[:,0].max())*sx),min(page_size.height,float(points[:,1].max())*sy)]
    for part in selected:
        box=part['provenance'][0]['bbox'];l,t,r,b=unmap([box['l'],box['t'],box['r'],box['b']]);part['provenance'][0]['bbox'].update(l=l,t=t,r=r,b=b)
        part['orientation']={'rotation':turn,'deskew':round(skew,3),'perspective_corrected':rectified,'quality':round(best[0],4)}
        for cell in part.get('cells',[]):cell['bbox']=unmap(cell['bbox'])
    return selected
