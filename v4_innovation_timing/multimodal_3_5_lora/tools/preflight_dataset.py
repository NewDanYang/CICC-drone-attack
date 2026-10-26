"""Exercise official preprocessing directly, avoiding its random retry on errors."""
import json,sys
from pathlib import Path
import torch
from PIL import Image
from torchvision import transforms
from transformers import AutoConfig, AutoTokenizer

root=Path('/root/gpufree-data/tcei_lora35')
sys.path.insert(0,str(root/'official/FM9G4B-V/finetune'))
from dataset import preprocess
torch.set_num_threads(2)
base='/home/ubuntu/model/FM9G4B-V'
tok=AutoTokenizer.from_pretrained(base,trust_remote_code=True,local_files_only=True)
config=AutoConfig.from_pretrained(base,trust_remote_code=True,local_files_only=True)
transform=transforms.Compose([transforms.ToTensor(),transforms.Normalize((.5,.5,.5),(.5,.5,.5))])
rows=[]
for split in ['train','validation']:
    for row in json.loads((root/'data'/f'{split}.json').read_text()):
        out=preprocess({'<image>':Image.open(row['image']).convert('RGB')},row['conversations'],tok,transform,
            slice_config=config.slice_config.to_dict(),patch_size=config.patch_size,query_nums=config.query_num,
            batch_vision=config.batch_vision_input,max_length=2048)
        labels=(out['target']!=-100).sum().item()
        assert labels>0 and len(out['image_bound'])>0 and len(out['pixel_values'])>0,row['id']
        assert len(out['input_ids'])<2048,'Truncation'
        rows.append(dict(id=row['id'],split=split,tokens=len(out['input_ids']),supervised_tokens=labels,
            image_bounds=len(out['image_bound']),image_slices=len(out['pixel_values'])))
dest=root/'preflight_dataset.json';dest.write_text(json.dumps(rows,indent=2)+'\n')
print('PASS records',len(rows),'supervised_tokens_min',min(r['supervised_tokens'] for r in rows))
