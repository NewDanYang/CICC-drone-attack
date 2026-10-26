"""Extract clean archived camera frames with timestamp-matched OFFLINE YOLO proposals.

Proposals are NOT trusted labels until visual review. Never imports ROS/YOLO.
"""
import hashlib, io, json, tarfile
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parents[1] / 'evidence' / 'data'
OUT.mkdir(parents=True, exist_ok=True)
rows=[]
for archive in sorted((ROOT/'multimodal_3_3/evidence/v2/trials').glob('*baseline.tar.gz')):
    # ROOT is v4_innovation_timing.
    with tarfile.open(archive) as tar:
        names=set(tar.getnames())
        events=[json.loads(line) for line in tar.extractfile('session/audit/events.jsonl')]
        objects={round(e['stamp'],5):e for e in events if e['event']=='objects' and e['topic']=='yolo'}
        for e in events:
            if e['event']!='image' or 'session/audit/'+e['file'] not in names: continue
            obj=objects.get(round(e['header_stamp'],5))
            if obj is None: continue
            proposals=[o for o in obj['objects'] if o['name'].endswith('_balloon') and o['score']>=.80]
            if not proposals: continue
            raw=tar.extractfile('session/audit/'+e['file']).read()
            assert hashlib.sha256(raw).hexdigest()==e['sha256']
            identity=archive.name[:-7]+'_'+Path(e['file']).stem
            rows.append(dict(id=identity,trial=archive.name[:-7],file=identity+'.jpg',
                archive=str(archive.relative_to(ROOT.parent)).replace('\\','/'),member='session/audit/'+e['file'],
                sha256=e['sha256'],stamp=e['header_stamp'],objects_stamp=obj['stamp'],proposals=proposals))
            (OUT/(identity+'.jpg')).write_bytes(raw)
(OUT/'pool.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(frames=len(rows),trials=dict(Counter(r['trial'] for r in rows)),
    objects=dict(Counter(o['name'] for r in rows for o in r['proposals']))),indent=2))

# Keep review sheets manageable, full-frame and zoomed proposal side by side.
for group in range(0,len(rows),8):
    sheet=Image.new('RGB',(1280,4*280),'white');draw=ImageDraw.Draw(sheet)
    for i,row in enumerate(rows[group:group+8]):
        x=(i%2)*640;y=(i//2)*280
        im=Image.open(OUT/row['file']).convert('RGB');small=im.resize((320,240))
        sheet.paste(small,(x,y+25));draw.text((x+2,y+2),f"{group+i:03d} {row['id']}",fill='black')
        for j,o in enumerate(row['proposals']):
            b=o['bbox'];pad=10
            crop=im.crop((max(0,b[0]-pad),max(0,b[1]-pad),min(640,b[2]+pad),min(480,b[3]+pad)))
            crop.thumbnail((145,190));sheet.paste(crop,(x+325+(j%2)*155,y+45+(j//2)*105))
            draw.text((x+325+(j%2)*155,y+27+(j//2)*105),o['name']+' '+str(b),fill='black')
        d=ImageDraw.Draw(small)
        for o in row['proposals']: d.rectangle([v/2 for v in o['bbox']],outline='yellow',width=1)
        sheet.paste(small,(x,y+25))
    sheet.save(OUT/f'review_{group//8:02d}.jpg',quality=92)
