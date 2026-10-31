"""Recompute recognition-to-control evidence without ROS or model imports."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def rows(path):
    if not path.exists(): return []
    result=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        try: result.append(json.loads(line))
        except json.JSONDecodeError: pass # An active writer may have a partial last row.
    return result


def summarize(session):
    model=[]
    for path in sorted((session/'model').glob('*/audit.jsonl')): model.extend(rows(path))
    observer=rows(session/'audit/events.jsonl')
    decisions=[row for row in model if row.get('kind')=='decision']
    valid=[row for row in decisions if row.get('bbox') is not None]
    calls=[row for row in model if row.get('kind')=='model_call']
    inputs=[row['images_per_item'] for row in model if row.get('kind')=='processor_input']
    consumed=[row for row in observer if row.get('event')=='rosout' and 'MULTIMODAL_PIXEL ' in row.get('message','')]
    published=[row for row in observer if row.get('event')=='objects' and row.get('topic')=='multimodal' and row.get('objects')]
    consumed_ids=Counter()
    for row in consumed:
        match=re.search(r'source=fm9g:([^ :]+):([^ ]+)',row['message'])
        if match: consumed_ids[match[2]]+=1
    sources=[row for row in model if row.get('kind')=='model_source']
    image_hashes={row.get('rgb_pixels_sha256') for row in observer if row.get('event')=='image'}
    snapshots=rows(session/'scene_snapshots.jsonl')
    started=[row for row in observer if row.get('event')=='rosout' and 'MULTIMODAL_STAGE_START' in row.get('message','')]
    stopped=[row for row in observer if row.get('event')=='rosout' and 'MULTIMODAL_STAGE_STOP' in row.get('message','')]
    start=started[0]['wall_time'] if started else None
    stop=stopped[-1]['wall_time'] if stopped else None
    from PIL import Image
    captures=[r for r in observer if r.get('event') in ('window_screenshot','blank_window_screenshot')]
    visible=0;blank=0;unavailable=0
    for capture in captures:
        path=session/'audit'/capture['file']
        if not path.exists():unavailable+=1;continue
        with Image.open(path) as frame:
            w,h=frame.size
            extrema=frame.convert('RGB').crop((w//10,h//5,9*w//10,4*h//5)).getextrema()
            nonblank=max(channel[1] for channel in extrema)>1
        if nonblank:visible+=1
        else:blank+=1
    report={'session':str(session),'sources':len(sources),'model_calls':len(calls),
            'batch_sizes':dict(Counter(r['batch_size'] for r in calls)),
            'processor_items':sum(len(x) for x in inputs),
            'image_count_violations':sum(any(n!=1 for n in counts) for counts in inputs),
            'decisions':len(decisions),'valid_decisions':len(valid),
            'decision_modes':dict(Counter(r.get('mode') for r in decisions)),
            'consumed_logs':len(consumed),'consumed_ids':dict(consumed_ids),
            'matched_decision_consumption':sum(r['decision'] in consumed_ids for r in valid),
            'published_valid_messages':len(published),
            'actual_window_screenshots':visible,'recorded_window_captures':len(captures),
            'blank_window_captures':blank,'unavailable_window_files':unavailable,
            'captured_images':sum(r.get('event')=='image' for r in observer),
            'source_hash_matches':sum(r.get('pixels_sha256') in image_hashes for r in sources),
            'image_input_clocks':[r for r in model if r.get('kind')=='camera_contract'],
            'gate_start':start,'gate_stop':stop,
            'scene_counts':[{'phase':r['phase'],'count':r['reported_count'],'actors':r['actor_ids']} for r in snapshots],
            'errors':[r for r in model if r.get('kind') in ('inference_error','discard_inactive')],
            'latest_decisions':[{k:v for k,v in r.items() if k in ('decision','color','bbox','model_box','mode','source_age_s','latency_s')} for r in decisions[-5:]]}
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('session',type=Path)
    args=parser.parse_args()
    print(json.dumps(summarize(args.session),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
