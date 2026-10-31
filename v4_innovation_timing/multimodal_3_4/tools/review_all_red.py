"""Make blinded contact sheets for all red source frames, preserving raw PNGs."""
import argparse,io,json,tarfile
from pathlib import Path
from PIL import Image,ImageDraw

p=argparse.ArgumentParser();p.add_argument('diagnosis',type=Path);p.add_argument('archives',type=Path);args=p.parse_args()
out=args.diagnosis/'red_all';out.mkdir(exist_ok=True)
rows=[r for r in json.loads((args.diagnosis/'decision_index.json').read_text(encoding='utf-8')) if r['color']=='red']
rows.sort(key=lambda r:(r['trial'],r['time']))
sources={}
for trial in sorted({r['trial'] for r in rows}):
    with tarfile.open(args.archives/(trial+'.tar.gz')) as archive:
        for row in (r for r in rows if r['trial']==trial):
            data=archive.extractfile(row['source_image']).read()
            (out/(row['decision']+'.png')).write_bytes(data);sources[row['decision']]=data
review=[]
for page in range((len(rows)+11)//12):
    canvas=Image.new('RGB',(1280,798),'white');draw=ImageDraw.Draw(canvas)
    for i,row in enumerate(rows[page*12:(page+1)*12]):
        im=Image.open(io.BytesIO(sources[row['decision']])).convert('RGB');im.thumbnail((320,240))
        x=i%4*320;y=i//4*266;canvas.paste(im,(x,y+24))
        draw.text((x+3,y+3),f"R{page*12+i+1:03d} {row['decision']}",fill='black')
        review.append(dict(number=page*12+i+1,decision=row['decision'],trial=row['trial'],
            source_sha256=row['source_sha256'],image=row['decision']+'.png'))
    canvas.save(out/f'contact_{page+1:02d}.jpg',quality=94)
(out/'index.json').write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
print('Red images',len(rows),'pages',(len(rows)+11)//12)
