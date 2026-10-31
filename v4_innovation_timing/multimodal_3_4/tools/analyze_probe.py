"""Offline verification, paired scoring and clearly labeled diagnostic overlays."""
import argparse,ast
from collections import Counter
import csv,hashlib,io,json,math,statistics,tarfile
from pathlib import Path
from PIL import Image,ImageDraw

p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args()
root=args.root;data=root/'evidence'
receipt=json.loads((data/'probe_receipt.json').read_text(encoding='utf-8'))
archive_path=data/'probe_evidence.tar.gz'
assert archive_path.stat().st_size==receipt['bytes']
assert hashlib.sha256(archive_path.read_bytes()).hexdigest()==receipt['sha256']
cases=json.loads((data/'red_probe_input/cases.json').read_text(encoding='utf-8'))
index={r['decision']:r for r in json.loads((data/'diagnosis/decision_index.json').read_text(encoding='utf-8'))}
out=data/'probe_analysis';out.mkdir(exist_ok=True)
with tarfile.open(archive_path) as archive:
    manifest=json.load(archive.extractfile('MANIFEST.json'))
    assert set(archive.getnames())=={'MANIFEST.json'}|{r['path'] for r in manifest}
    for item in manifest:
        content=archive.extractfile(item['path']).read()
        assert len(content)==item['bytes'] and hashlib.sha256(content).hexdigest()==item['sha256']
    config=json.load(archive.extractfile('probe_results/config.json'))
    rows=[json.loads(s) for s in archive.extractfile('probe_results/predictions.jsonl').read().decode().splitlines()]
    calls=[json.loads(s) for s in archive.extractfile('probe_results/calls.jsonl').read().decode().splitlines()]
    original_scoring=json.load(archive.extractfile('probe_results/scored.json'))
    original_summary=json.load(archive.extractfile('probe_results/summary.json'))
    assert len(rows)==24 and [r['decision'] for r in rows]==[r['decision'] for r in cases]
    assert hashlib.sha256((data/'red_probe_input/cases.json').read_bytes()).hexdigest()==config['cases_sha256']
    # Execute only the archived pure parsing/scoring functions, never its main.
    source=archive.extractfile('probe_two_step.py').read()
    tree=ast.parse(source);functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'strict_json','parse_bbox','compare'}]
    ns=dict(json=json,math=math)
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),'archived_pure_functions','exec'),ns)
    pair=[];overlays=[]
    for case,row,scored in zip(cases,rows,original_scoring):
        assert case['decision']==row['decision']==scored['decision']
        assert row['source_sha256']==case['source_sha256']
        source_png=archive.extractfile('probe_results/inputs/'+case['decision']+'_full.png').read()
        assert hashlib.sha256(source_png).hexdigest()==case['source_sha256']
        frame=Image.open(io.BytesIO(source_png)).convert('RGB')
        if row['roi']:
            crop=frame.crop(row['roi'])
            actual=Image.open(archive.extractfile('probe_results/inputs/'+case['decision']+'_bbox.png')).convert('RGB')
            assert crop.size==actual.size and crop.tobytes()==actual.tobytes()
            assert ns['parse_bbox'](row['bbox_raw'],row['roi'])==row['bbox']
        metric=ns['compare'](row['bbox'],case['visible_bbox'])
        assert metric==scored['geometry']
        old=index[case['decision']]
        old_metric=ns['compare'](old['bbox'],case['visible_bbox'])
        truth=case['visible_bbox'];correct_region=None;contained=None
        if truth:
            cx=(truth[0]+truth[2])/2
            correct_region=('left' if cx<640/3 else 'center' if cx<1280/3 else 'right')
            if row['roi']:
                a,b,c,d=row['roi'];x,y,z,w=truth;contained=a<=x<z<=c and b<=y<w<=d
            view=frame.copy();draw=ImageDraw.Draw(view)
            if row['roi']:draw.rectangle(row['roi'],outline='cyan',width=2)
            draw.rectangle(truth,outline='lime',width=3)
            if row['bbox']:draw.rectangle(row['bbox'],outline='magenta',width=3)
            draw.rectangle((0,0,640,25),fill='black')
            draw.text((5,7),case['decision']+' manual=green; predicted=magenta; ROI=cyan',fill='white')
            path=out/(case['decision']+'_overlay.png');view.save(path);overlays.append(view)
        full_prediction=ns['strict_json'](row['full_raw'])
        pair.append(dict(decision=case['decision'],trial=case['trial'],visibility=case['visibility'],
            manual_bbox=truth,original_frame_clipped=case['original_frame_clipped'],
            old_model_roi=old['model_box'],old_bbox=old['bbox'],old_geometry=old_metric,
            full_regions=full_prediction['balloons'],coarse_target=row['coarse_target'],
            coarse_region=row['coarse_region'],manual_region=correct_region,roi=row['roi'],roi_contains_manual_box=contained,
            new_bbox=row['bbox'],new_geometry=metric,
            total_latency_s=row['full_latency_s']+(row['bbox_latency_s'] or 0),
            full_latency_s=row['full_latency_s'],bbox_latency_s=row['bbox_latency_s'],error=row['error']))
    sources=[r for r in calls if r['kind']=='source'];answers=[r for r in calls if r['kind']=='answer']
    processors=[r for r in calls if r['kind']=='processor_input']
    for r in sources:
        content=archive.extractfile('probe_results/'+r['image']).read()
        im=Image.open(io.BytesIO(content)).convert('RGB')
        assert hashlib.sha256(content).hexdigest()==r['sha256']
        assert hashlib.sha256(im.tobytes()).hexdigest()==r['pixels_sha256']
    assert len({r['model_instance'] for r in answers})==1
    assert all(r['images_per_item']==[1] for r in processors)
    before=archive.extractfile('deployment_before.md5').read()
    after=archive.extractfile('deployment_after.md5').read();assert before==after
    for name in ('config.json','summary.json','predictions.jsonl','scored.json','calls.jsonl'):
        (out/name).write_bytes(archive.extractfile('probe_results/'+name).read())
    (out/'deployment_before.md5').write_bytes(before);(out/'deployment_after.md5').write_bytes(after)
visible=[r for r in pair if r['visibility']=='visible'];absent=[r for r in pair if r['visibility']=='not_visible']
full=[r for r in visible if not r['original_frame_clipped']];clipped=[r for r in visible if r['original_frame_clipped']]
def geometry_stats(part):
    metrics=[r['new_geometry'] for r in part if r['new_geometry']]
    return dict(n=len(part),nonempty=sum(r['new_bbox'] is not None for r in part),
        usable=sum(bool(r['new_geometry'] and r['new_geometry']['passes_geometry']) for r in part),
        min_iou=min(r['iou'] for r in metrics),median_iou=statistics.median(r['iou'] for r in metrics),max_iou=max(r['iou'] for r in metrics),
        center_error_min_px=min(r['center_error_px'] for r in metrics),center_error_median_px=statistics.median(r['center_error_px'] for r in metrics),
        center_error_max_px=max(r['center_error_px'] for r in metrics))
summary=dict(original_gate_summary=original_summary,full_visible=geometry_stats(full),source_clipped_visible=geometry_stats(clipped),
    all_visible=geometry_stats(visible),coarse_region_correct=sum(r['coarse_region']==r['manual_region'] for r in visible),
    expanded_roi_contains_visible_box=sum(r['roi_contains_manual_box'] is True for r in visible),
    absent_unknown_balloon_responses=sum(any(o['color']=='unknown' for o in r['full_regions']) for r in absent),
    old_visible_roi_nonempty=sum(r['old_model_roi'] is not None for r in visible),
    old_visible_bbox_nonempty=sum(r['old_bbox'] is not None for r in visible),
    old_visible_bbox_geometry_pass=sum(bool(r['old_geometry'] and r['old_geometry']['passes_geometry']) for r in visible),
    all_verified_archive_members=len(manifest),actual_processor_calls=len(processors),one_model_instance_verified=True,
    all_actual_images_and_crops_verified=True,source_pixel_hashes_verified=len(sources),deployment_11_md5_unchanged=True,
    visible_latency_min_s=min(r['total_latency_s'] for r in visible),visible_latency_median_s=statistics.median(r['total_latency_s'] for r in visible),
    visible_latency_max_s=max(r['total_latency_s'] for r in visible),scope='24 correlated old red frames, diagnostic; no flight or independent acceptance')
(out/'paired_results.json').write_text(json.dumps(pair,indent=2)+'\n',encoding='utf-8')
(out/'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
flat=[{k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in pair]
with (out/'paired_results.csv').open('w',encoding='utf-8',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
montage=Image.new('RGB',(1280,960),'white')
for i,view in enumerate(overlays):view.thumbnail((320,480));montage.paste(view,((i%4)*320,(i//4)*480))
montage.save(out/'geometry_contact_sheet.jpg',quality=94)
print(json.dumps(summary,indent=2))
