"""FM9G-only image localization by uniformly tiled semantic queries.

No detector, HSV threshold, contour proposal, world coordinate or flight command
is used here. All semantic observations come from the supplied model callable.
"""
import json
import math
import re
from PIL import Image, ImageDraw

COARSE_PROMPT = (
    '图片被白线分成9格，每格左上角写了编号1到9。请列出实际可见的气球颜色和气球中心所在格的编号。'
    '只输出JSON：{"balloons":[{"color":"red/blue/purple","cell":1}]}。'
    'color只能red、blue、purple之一，cell只能1到9。没有气球则输出{"balloons":[]}。不要解释。')
TILE_PROMPT = ('这张图片中有没有气球？如果有，只回复red balloon、purple balloon或blue balloon。'
               '如果没有气球，只回复no balloon。平坦的墙壁、天空和小车不是气球。不要解释。')
COLOR_PROMPT = ('图中气球是什么颜色？只回答一个英文单词：red、purple、blue 或 none。'
                '无气球时回答none。小车、墙壁、天空不是气球。')
DETAIL_PROMPT = ('这是气球附近的局部细节图。请判断是否包含鲜艳的气球表面，即使只是一小部分。'
                 '只回复red balloon、purple balloon、blue balloon或no balloon。'
                 '平坦的灰蓝色墙壁、天空、灰白地面和黑色小车属于背景，回答no balloon。不要解释。')
COLORS = {'red', 'purple', 'blue'}


def one_json(answer):
    text = str(answer).strip()
    # Preserve raw output in the audit log; permit prose around ONE complete
    # JSON object, never a guessed repair of missing or mismatched fields.
    decoder = json.JSONDecoder()
    decoded = []
    for match in re.finditer(r'\{', text):
        try:
            value, length = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and 'balloons' in value:
            decoded.append(value)
    if len(decoded) != 1:
        raise ValueError('Expected one balloons JSON object')
    return decoded[0]


def parse_coarse(answer):
    obj = one_json(answer)
    if set(obj) != {'balloons'} or not isinstance(obj['balloons'], list):
        raise ValueError('Invalid coarse schema')
    rows = []
    for item in obj['balloons']:
        if not isinstance(item, dict) or set(item) != {'color', 'cell'}:
            raise ValueError('Invalid coarse record')
        if item['color'] not in COLORS or type(item['cell']) is not int or not 1 <= item['cell'] <= 9:
            raise ValueError('Invalid color/cell')
        rows.append(item)
    return rows


def parse_tile(answer):
    text = str(answer).strip().lower().strip('`\"\' .。\n')
    values = {'red balloon': 'red', 'purple balloon': 'purple', 'blue balloon': 'blue',
              'no balloon': None, '红色气球': 'red', '紫色气球': 'purple', '蓝色气球': 'blue',
              '无气球': None, '没有气球': None,
              'red':'red','purple':'purple','blue':'blue','none':None,
              '红色':'red','紫色':'purple','蓝色':'blue'}
    if text not in values:
        raise ValueError('Invalid semantic tile answer: '+repr(text))
    return values[text]


def affirmative_presence(answer):
    text=str(answer).strip().strip(' .。')
    return bool(re.fullmatch(
        r'(?:是的[，, ]*)?(?:(?:这张图片|图片|这张图)中)?有(?:一个|一只)?'
        r'(?:(?:红色|紫色|蓝色)的?)?气球',text))


def parse_color_reply(answer):
    try: return parse_tile(answer)
    except ValueError: pass
    text=str(answer).strip().strip(' .。')
    match=re.fullmatch(r'(?:(?:图中|图片中|这个|这只)(?:的)?)?气球(?:的?颜色)?是(红色|紫色|蓝色)(?:的)?',text)
    if not match: raise ValueError('Ambiguous color clarification: '+repr(text))
    return {'红色':'red','紫色':'purple','蓝色':'blue'}[match[1]]


def semantic_labels(images,infer,audit=lambda **kwargs:None):
    """Clarify only the model's own affirmative balloon-presence answers.

    Never infer a color from the requested mission, from pixels, or from a
    negative/ambiguous response. Both observations use the SAME source crop.
    """
    answers=infer(images,TILE_PROMPT)
    if len(answers)!=len(images): raise ValueError('Batch answer count mismatch')
    labels=[];clarify=[]
    for index,answer in enumerate(answers):
        try: labels.append(parse_tile(answer))
        except ValueError:
            labels.append(None)
            if affirmative_presence(answer): clarify.append(index)
    if clarify:
        replies=infer([images[i] for i in clarify],COLOR_PROMPT)
        if len(replies)!=len(clarify): raise ValueError('Clarification count mismatch')
        for index,reply in zip(clarify,replies):
            try: labels[index]=parse_color_reply(reply)
            except ValueError: labels[index]=None
        audit(kind='color_clarification',indices=clarify,presence_answers=[answers[i] for i in clarify],
              color_answers=replies,labels=[labels[i] for i in clarify])
    return labels,answers


def clipped_box(box, size):
    width, height = size
    x1,y1,x2,y2 = box
    result = [max(0,int(math.floor(x1))), max(0,int(math.floor(y1))),
              min(width,int(math.ceil(x2))), min(height,int(math.ceil(y2)))]
    if result[0] >= result[2] or result[1] >= result[3]:
        raise ValueError('Empty ROI')
    return result


def expand(box, fraction, size):
    x1,y1,x2,y2=box
    dx,dy=(x2-x1)*fraction,(y2-y1)*fraction
    return clipped_box((x1-dx,y1-dy,x2+dx,y2+dy),size)


def nine_grid(image):
    result = image.copy()
    width,height=result.size
    draw=ImageDraw.Draw(result)
    for i in (1,2):
        draw.line((round(i*width/3),0,round(i*width/3),height-1),fill='white',width=2)
        draw.line((0,round(i*height/3),width-1,round(i*height/3)),fill='white',width=2)
    for row in range(3):
        for col in range(3):
            x,y=round(col*width/3)+4,round(row*height/3)+4
            draw.rectangle((x,y,x+22,y+22),fill='black')
            draw.text((x+7,y+4),str(row*3+col+1),fill='white')
    return result


def components(indices, grid=4):
    pending=set(indices)
    result=[]
    while pending:
        seed=pending.pop()
        group={seed}
        todo=[seed]
        while todo:
            index=todo.pop()
            row,col=divmod(index,grid)
            neighbors={r*grid+c for r in range(row-1,row+2) for c in range(col-1,col+2)
                       if 0<=r<grid and 0<=c<grid}
            added=neighbors & pending
            pending-=added
            group|=added
            todo.extend(added)
        result.append(group)
    return result


class TiledLocalizer:
    def __init__(self, infer, audit=lambda **kwargs: None):
        self.infer=infer
        self.audit=audit

    def locate(self, image, color, roi=None, levels=3):
        if color not in COLORS:
            raise ValueError('Invalid requested color')
        if roi is None:
            # Number-reading and direct coordinate regression both failed the
            # development probe. Scan ALL equally sized tiles, independently;
            # no predicted coarse location is trusted to hide image regions.
            roi=[0,0,*image.size]
        else:
            roi=clipped_box(roi,image.size)
        for level in range(levels):
            x1,y1,x2,y2=roi
            boxes=[]
            crops=[]
            for row in range(4):
                for col in range(4):
                    box=clipped_box([x1+col*(x2-x1)/4,y1+row*(y2-y1)/4,
                                     x1+(col+1)*(x2-x1)/4,y1+(row+1)*(y2-y1)/4],image.size)
                    boxes.append(box)
                    crops.append(image.crop(box))
            answers=self.infer(crops,TILE_PROMPT if level==0 else DETAIL_PROMPT)
            if len(answers)!=len(boxes):
                raise ValueError('Batch answer count mismatch')
            labels=[]
            for answer in answers:
                try: labels.append(parse_tile(answer))
                except ValueError: labels.append(None)
            groups=components(i for i,value in enumerate(labels) if value==color)
            self.audit(kind='tiles',level=level,roi=roi,boxes=boxes,answers=answers,labels=labels,
                       components=[sorted(g) for g in groups])
            if not groups:
                return None
            # This uses only model outputs. Prefer a coherent group; ties keep
            # the spatial prior selected by this SAME model at the coarse step.
            midx,midy=(x1+x2)/2,(y1+y2)/2
            def rank(group):
                cx=sum((boxes[i][0]+boxes[i][2])/2 for i in group)/len(group)
                cy=sum((boxes[i][1]+boxes[i][3])/2 for i in group)/len(group)
                return (-len(group),(cx-midx)**2+(cy-midy)**2)
            # Once the model has selected a local ROI, keep separated visible
            # pieces of the same balloon (e.g. specular highlights split the
            # semantic mask). No image/color heuristic fills these decisions.
            group=min(groups,key=rank) if level==0 else set().union(*groups)
            box=[min(boxes[i][0] for i in group),min(boxes[i][1] for i in group),
                 max(boxes[i][2] for i in group),max(boxes[i][3] for i in group)]
            if level+1==levels:
                return box
            roi=expand(box,0.25,image.size)
        return None


class OverlapLocalizer:
    """One local area from the union of connected FM9G-positive views."""
    def __init__(self,infer,audit=lambda **kwargs:None):
        self.infer,self.audit=infer,audit

    def locate(self,image,color):
        if color not in COLORS: raise ValueError('Invalid requested color')
        width,height=image.size
        boxes=[[round(col*width*.2),round(row*height*.2),
                round((col*.2+.4)*width),round((row*.2+.4)*height)]
               for row in range(4) for col in range(4)]
        labels,answers=semantic_labels([image.crop(box) for box in boxes],self.infer,self.audit)
        groups=components(i for i,label in enumerate(labels) if label==color)
        positive=[boxes[i] for i in groups[0]] if len(groups)==1 else []
        box=([min(b[0] for b in positive),min(b[1] for b in positive),
              max(b[2] for b in positive),max(b[3] for b in positive)] if positive else None)
        if box and (box[2]-box[0])*(box[3]-box[1])>.75*width*height:box=None
        self.audit(kind='overlapping_tiles',boxes=boxes,answers=answers,labels=labels,
                   components=[sorted(group) for group in groups],model_box=box,geometry='local_union')
        return box
