#!/usr/bin/env python3
import hashlib,json,shutil
from pathlib import Path

root=Path('/home/ubuntu/multimodal_v2')
pack=root/'v2'
backup=Path('/home/ubuntu/multimodal_v2_backup_20261101_stage_d_package')
if not backup.exists():
    backup.mkdir(parents=True)
    for rel in ['v2/manifest.json','v2/runtime.py','v2/tracking.py','v2/presence.py','patches/deploy_v2.py']:
        src=root/rel
        if src.exists():
            dest=backup/rel
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dest)

def md5(p): return hashlib.md5(Path(p).read_bytes()).hexdigest()
manifest=json.loads((pack/'manifest.json').read_text(encoding='utf-8'))
# Carry the already deployed fixed package into the switch package.
for name in ['runtime.py','tracking.py','presence.py']:
    src=Path('/home/ubuntu/multimodal_v2/p12e_stage_b/v2')/name
    shutil.copy2(src, pack/name)
    manifest['package_md5']['v2/'+name]=md5(pack/name)

deploy=root/'patches/deploy_v2.py'
text=deploy.read_text(encoding='utf-8')
old="('localizer.py','tracking.py','runtime.py','refinement.py','geometry.py')"
new="('localizer.py','tracking.py','runtime.py','refinement.py','geometry.py','presence.py')"
if text.count(old)!=3:
    raise SystemExit(f'deploy loop count={text.count(old)}')
text=text.replace(old,new)
deploy.write_bytes(text.encode('utf-8'))
manifest['package_md5']['patches/deploy_v2.py']=md5(deploy)
(pack/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
(backup/'before_md5.tsv').write_text('\n'.join(f'{md5(backup/rel)}\t{rel}' for rel in ['v2/manifest.json','v2/runtime.py','v2/tracking.py','v2/presence.py','patches/deploy_v2.py'] if (backup/rel).exists())+'\n',encoding='ascii')
(backup/'after_md5.tsv').write_text('\n'.join(f'{md5(root/rel)}\t{rel}' for rel in ['v2/manifest.json','v2/runtime.py','v2/tracking.py','v2/presence.py','patches/deploy_v2.py'])+'\n',encoding='ascii')
print('package_backup='+str(backup))
print((backup/'after_md5.tsv').read_text())
