"""Verify sealed runtime, demo packages, base weights and official training sources."""
import hashlib, json, subprocess
from pathlib import Path
root=Path('/root/gpufree-data/tcei_lora35')
dest=root/'runtime_integrity_comparison.json'
if dest.exists():raise RuntimeError('Refuse overwrite')
subprocess.run(['/opt/conda/envs/demo/bin/python',str(root/'tools/audit_runtime.py'),'runtime_after'],check=True)
before=json.loads((root/'runtime_before.json').read_text());after=json.loads((root/'runtime_after.json').read_text())
changed=[p for p in before['files'] if before['files'][p]!=after['files'].get(p)]
weight=Path('/home/ubuntu/model/FM9G4B-V/pytorch_model.bin');h=hashlib.sha256()
with weight.open('rb') as f:
    for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
sha=h.hexdigest();(root/'base_weights_after.sha256').write_text(sha+'  '+str(weight)+'\n')
expected=(root/'base_weights_before.sha256').read_text().split()[0]
source_diff=subprocess.check_output(['git','-C',str(root/'official'),'diff','HEAD','--','FM9G4B-V/finetune']).decode()
record=dict(runtime_files_checked=len(before['files']),changed_files=changed,
    demo_packages_before=before['demo_packages'],demo_packages_after=after['demo_packages'],
    base_weights_before=expected,base_weights_after=sha,
    official_training_tracked_diff=source_diff)
record['passed']=not changed and before['demo_packages']==after['demo_packages'] and sha==expected and not source_diff
dest.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
assert record['passed']
