"""Run the frozen base/adapter held-out comparison sequentially, once."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

ROOT=Path('/root/gpufree-data/tcei_lora35')
p=argparse.ArgumentParser();p.add_argument('--detach',action='store_true');a=p.parse_args()
if a.detach:
    receipt=ROOT/'evaluation_process.json'
    if receipt.exists():raise RuntimeError('Evaluation already launched')
    with (ROOT/'paired_runner.log').open('x') as stream:
        proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve())],cwd=ROOT,
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,stdin=subprocess.DEVNULL)
    record=dict(pid=proc.pid,started=time.time(),command='run_pair.py')
    receipt.write_text(json.dumps(record)+'\n');print(json.dumps(record));sys.exit(0)

chosen=json.loads((ROOT/'training_receipt.json').read_text())['selected_checkpoint']
env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='2')
try:
    for name,extra in [('base_test',[]),('adapter_test',['--adapter',chosen])]:
        command=[str(ROOT/'venv/bin/python'),str(ROOT/'tools/evaluate.py'),
            '--data',str(ROOT/'data'),'--split','test','--output',str(ROOT/name)]+extra
        print(json.dumps(dict(start=name,time=time.time(),command=command)),flush=True)
        with (ROOT/(name+'.log')).open('x') as stream:
            subprocess.run(command,env=env,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        print(json.dumps(dict(completed=name,time=time.time())),flush=True)
    subprocess.run([str(ROOT/'venv/bin/python'),str(ROOT/'tools/analyze_pair.py'),
        '--data',str(ROOT/'data'),'--base',str(ROOT/'base_test'),
        '--adapter',str(ROOT/'adapter_test'),'--output',str(ROOT/'paired_analysis')],check=True,cwd=ROOT,env=env)
except Exception as error:
    (ROOT/'evaluation_failed.json').write_text(json.dumps(dict(error=repr(error),time=time.time()))+'\n');raise
(ROOT/'evaluation_complete.json').write_text(json.dumps(dict(time=time.time(),selected_checkpoint=chosen))+'\n')
