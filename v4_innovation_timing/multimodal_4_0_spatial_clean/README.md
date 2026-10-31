# FM9G4B-V 4.0 spatial-clean experiment

This directory contains the reproducible dataset builders, fixed MLA LoRA
trainer wrapper, launchers, and copied evaluation evidence. The large adapter
files stay on the research server and are identified by SHA-256 in `REPORT.md`.

On the server, after the real capture data and the official FM9G4B-V checkout
are present:

```bash
python3 tools/build_clean_native_dataset.py
bash tools/run_train.sh
python /root/gpufree-data/mm38_config_fix/tools/evaluate_native_box.py \
  --data /root/gpufree-data/mm40_spatial_clean/data \
  --split validation --adapter /root/gpufree-data/mm40_spatial_clean/output_lora \
  --output /root/gpufree-data/mm40_spatial_clean/eval_validation
```

The second controlled candidate is built with
`build_run8_run9_mix.py` and launched with `run_train_mix.sh`. The evaluator
must be run with a fresh output directory because it refuses to overwrite
existing evidence.
