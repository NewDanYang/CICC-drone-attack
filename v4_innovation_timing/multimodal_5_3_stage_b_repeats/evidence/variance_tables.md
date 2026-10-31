# Stage B variance tables

Core trials: 45; extra controlled trials: 10.

| Color | n | All centre_pct values | Median | Worst | Threshold | Median pass | Worst >=30 |
|---|---:|---|---:|---:|---:|---|---|
| red | 15 | [None, 83.9, 87.2, 29.8, None, 80.6, 68.1, 83.9, None, 69.4, None, 25.5, 85.1, None, 82.3] | 81.44999999999999 | 25.5 | 68.0 | True | False |
| purple | 15 | [42.6, 60.3, 52.2, 53.6, 42.6, 70.6, 57.1, 38.3, 56.5, 40.4, 80.2, 55.1, 38.3, 63.8, 61.9] | 55.1 | 38.3 | 51.0 | True | True |
| blue | 15 | [75.0, 22.2, 84.6, 81.2, 63.0, 78.8, 76.9, 73.4, 63.0, 63.0, 84.6, 79.7, 78.8, 63.0, 78.1] | 76.9 | 22.2 | 62.0 | True | False |

## Per-run values

- `01_r1_red_baseline`: [None, None, None, None, None]
- `04_r1_purple_baseline`: [42.6, 42.6, 38.3, 40.4, 38.3]
- `05_r1_blue_baseline`: [75.0, 81.2, 73.4, 79.7, 78.1]
- `08_r2_red_baseline`: [83.9, 80.6, 83.9, 69.4, 82.3]
- `09_r2_purple_baseline`: [60.3, 70.6, 57.1, 80.2, 61.9]
- `12_r2_blue_baseline`: [22.2, 63.0, 63.0, 63.0, 63.0]
- `13_r3_red_baseline`: [87.2, 29.8, 68.1, 25.5, 85.1]
- `16_r3_purple_baseline`: [52.2, 53.6, 56.5, 55.1, 63.8]
- `17_r3_blue_baseline`: [84.6, 78.8, 76.9, 84.6, 78.8]

## Order comparison

- `01_r1_red_baseline` canonical=None; shuffled=[None, None, None, None]; delta=[None, None, None, None]
- `04_r1_purple_baseline` canonical=42.6; shuffled=[42.6, 38.3, 40.4, 38.3]; delta=[0.0, -4.3, -2.2, -4.3]
- `05_r1_blue_baseline` canonical=75.0; shuffled=[81.2, 73.4, 79.7, 78.1]; delta=[6.2, -1.6, 4.7, 3.1]
- `08_r2_red_baseline` canonical=83.9; shuffled=[80.6, 83.9, 69.4, 82.3]; delta=[-3.3, 0.0, -14.5, -1.6]
- `09_r2_purple_baseline` canonical=60.3; shuffled=[70.6, 57.1, 80.2, 61.9]; delta=[10.3, -3.2, 19.9, 1.6]
- `12_r2_blue_baseline` canonical=22.2; shuffled=[63.0, 63.0, 63.0, 63.0]; delta=[40.8, 40.8, 40.8, 40.8]
- `13_r3_red_baseline` canonical=87.2; shuffled=[29.8, 68.1, 25.5, 85.1]; delta=[-57.4, -19.1, -61.7, -2.1]
- `16_r3_purple_baseline` canonical=52.2; shuffled=[53.6, 56.5, 55.1, 63.8]; delta=[1.4, 4.3, 2.9, 11.6]
- `17_r3_blue_baseline` canonical=84.6; shuffled=[78.8, 76.9, 84.6, 78.8]; delta=[-5.8, -7.7, 0.0, -5.8]

## GPU timing

- `acquire_sweep`: trial median range 450.479675-463.995392 ms; aggregate median 455.35362250000003 ms.
- `acquire_tiles`: trial median range 207.194489-211.31958 ms; aggregate median 209.586426 ms.
- `track_sweep`: trial median range 392.720154-398.90567 ms; aggregate median 395.49894700000004 ms.
