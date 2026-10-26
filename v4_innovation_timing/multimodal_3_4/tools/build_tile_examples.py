"""Preserve exact representative tile inputs and labeled browsing sheets."""
import argparse,hashlib,io,json,tarfile
from pathlib import Path
from PIL import Image,ImageDraw

p=argparse.ArgumentParser();p.add_argument('diagnosis',type=Path);p.add_argument('archives',type=Path);args=p.parse_args()
index={r['decision']:r for r in json.loads((args.diagnosis/'decision_index.json').read_text(encoding='utf-8'))}
chosen=['54a5442fc26f','34bb3292a5dc','b24228639a49','d270ad687e51','1c594737442c','044c40b0a1d3']
out=args.diagnosis/'tile_examples';out.mkdir(exist_ok=True);manifest=[]
for ident in chosen:
    row=index[ident];folder=out/ident;folder.mkdir(exist_ok=True)
    with tarfile.open(args.archives/(row['trial']+'.tar.gz')) as archive:
        source=Image.open(archive.extractfile(row['source_image'])).convert('RGB')
        log_name=next(n for n in archive.getnames() if n.startswith('session/model/') and n.endswith('/audit.jsonl'))
        events=[json.loads(s) for s in archive.extractfile(log_name).read().decode().splitlines()]
        call=next(r for r in events if r.get('kind')=='model_call' and r.get('decision')==ident and r['batch_size']==16)
    canvas=Image.new('RGB',(1024,4*216),'white');draw=ImageDraw.Draw(canvas)
    for i,box in enumerate(row['boxes']):
        image=source.crop(box);pixels=hashlib.sha256(image.tobytes()).hexdigest()
        assert pixels==call['image_pixels_sha256'][i]
        path=folder/f'{i:02d}.png';image.save(path)
        x=i%4*256;y=i//4*216;canvas.paste(image,(x,y+24))
        draw.text((x+3,y+5),f"{i:02d} label={row['labels'][i]}",fill='black')
        manifest.append(dict(decision=ident,tile=i,box=box,pixels_sha256=pixels,
            file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),file=path.relative_to(out).as_posix()))
    canvas.save(out/(ident+'_tiles.jpg'),quality=94)
(out/'tile_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('Representative source frames',len(chosen),'exact tiles',len(manifest))
