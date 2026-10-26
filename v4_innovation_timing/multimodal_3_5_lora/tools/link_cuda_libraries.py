"""Bridge inherited CUDA package libraries into the isolated venv, without editing demo.

pip --system-site-packages sees installed CUDA dependencies but a local nvidia
namespace (NCCL 2.19) shadows their library paths for torch 2.2's ELF loader.
Existing venv modules are never replaced, especially the pinned NCCL version.
"""
import json
from pathlib import Path
root=Path('/root/gpufree-data/tcei_lora35')
source=Path('/opt/conda/envs/demo/lib/python3.10/site-packages/nvidia')
dest=root/'venv/lib/python3.10/site-packages/nvidia'
rows=[]
for name in ['cublas','cuda_cupti','cuda_nvrtc','cuda_runtime','cudnn','cufft','curand','cusolver','cusparse','nvjitlink','nvtx']:
    path=dest/name
    if not path.exists():
        assert (source/name).is_dir()
        path.symlink_to(source/name,target_is_directory=True)
    rows.append(dict(link=str(path),target=str(path.resolve())))
(root/'cuda_library_links.json').write_text(json.dumps(rows,indent=2)+'\n')
print('CUDA library paths linked; demo source and venv NCCL untouched')
