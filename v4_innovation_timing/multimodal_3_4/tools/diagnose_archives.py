"""Local raw-log and crop audit of the frozen 3.3 candidate archives. No ROS/model."""
import argparse
from collections import Counter,defaultdict
import hashlib
import io
import json
from pathlib import Path
import statistics
import tarfile

from PIL import Image,ImageDraw


def main():
    p=argparse.ArgumentParser();p.add_argument('--archives',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    reviews=args.output/'review';reviews.mkdir(exist_ok=True)
    records=[];selected=[];raw_answers=Counter();prompts=Counter();hash_checks=0
    for path in sorted(args.archives.glob('*_candidate.tar.gz')):
        with tarfile.open(path) as archive:
            name=next(n for n in archive.getnames() if n.startswith('session/model/') and n.endswith('/audit.jsonl'))
            events=[json.loads(s) for s in archive.extractfile(name).read().decode().splitlines()]
            by_id=defaultdict(list)
            for event in events:
                if event.get('decision'):by_id[event['decision']].append(event)
            local=[]
            for decision in (e for e in events if e.get('kind')=='decision' and e['mode']=='initialization'):
                ident=decision['decision'];related=by_id[ident]
                source=next(r for r in related if r['kind']=='model_source')
                tiles=next(r for r in related if r['kind']=='overlapping_tiles')
                call=next(r for r in related if r['kind']=='model_call' and r['batch_size']==16)
                png=name.rsplit('/',1)[0]+'/'+source['image']
                content=archive.extractfile(png).read();assert hashlib.sha256(content).hexdigest()==source['image_sha256']
                im=Image.open(io.BytesIO(content)).convert('RGB')
                assert hashlib.sha256(im.tobytes()).hexdigest()==source['pixels_sha256']
                for i,box in enumerate(tiles['boxes']):
                    crop=im.crop(box)
                    assert list(crop.size)==call['image_sizes'][i]
                    assert hashlib.sha256(crop.tobytes()).hexdigest()==call['image_pixels_sha256'][i]
                    hash_checks+=1
                desired=[i for i,c in enumerate(tiles['labels']) if c==decision['color']]
                if decision['model_box'] is None:
                    reason=('no_target_positive_tiles' if not desired else
                            'disconnected_positive_tiles' if len(tiles['components'])!=1 else 'positive_union_too_large')
                else:reason='bbox_nonempty' if decision['bbox'] else 'geometry_unconfirmed'
                row=dict(trial=path.stem.removesuffix('.tar'),decision=ident,color=decision['color'],
                    time=source['wall_time'],source_image=png,source_sha256=source['image_sha256'],
                    source_pixels_sha256=source['pixels_sha256'],source_size=source['size'],
                    reason=reason,bbox=decision['bbox'],model_box=decision['model_box'],
                    positive_indices=desired,boxes=tiles['boxes'],answers=tiles['answers'],labels=tiles['labels'],
                    prompt=call['prompt'],latency_s=decision['latency_s'],
                    color_clarifications=[r for r in related if r['kind']=='color_clarification'])
                local.append(row);records.append(row);raw_answers.update(tiles['answers']);prompts[call['prompt']]+=1
            missing=[r for r in local if r['model_box'] is None]
            indices=sorted({round((len(missing)-1)*q/4) for q in range(5)}) if missing else []
            chosen=[missing[i] for i in indices]+[r for r in local if r['bbox'] is not None]
            rejected=[r for r in local if r['reason']=='geometry_unconfirmed']
            if rejected:chosen.append(rejected[0])
            for row in chosen:
                image_name=row['trial']+'__'+row['decision']+'.png'
                (reviews/image_name).write_bytes(archive.extractfile(row['source_image']).read())
                selected.append({k:row[k] for k in ('trial','decision','color','source_sha256')}|{'image':image_name})
    # Contact sheets deliberately hide model answers and outcome categories.
    ordered=sorted(selected,key=lambda r:(r['color'],r['trial'],r['decision']))
    for page in range((len(ordered)+11)//12):
        part=ordered[page*12:(page+1)*12]
        canvas=Image.new('RGB',(1280,3*266),'white');draw=ImageDraw.Draw(canvas)
        for i,row in enumerate(part):
            frame=Image.open(reviews/row['image']).convert('RGB');frame.thumbnail((320,240))
            x=i%4*320;y=i//4*266;canvas.paste(frame,(x,y+24))
            draw.text((x+4,y+3),f"{page*12+i+1:02d} {row['color']} {row['decision']}",fill='black')
        canvas.save(reviews/f'contact_{page+1:02d}.jpg',quality=94)
    (args.output/'decision_index.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'review_selection.json').write_text(json.dumps(ordered,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary=dict(initializations=len(records),reason_counts=dict(Counter(r['reason'] for r in records)),
        per_color={color:dict(Counter(r['reason'] for r in records if r['color']==color)) for color in ('red','purple','blue')},
        crop_pixel_hashes_verified=hash_checks,review_sample_count=len(ordered),
        prompts=dict(prompts),raw_answer_counts=dict(raw_answers.most_common()),
        target_positive_counts=dict(Counter(len(r['positive_indices']) for r in records)))
    (args.output/'log_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
