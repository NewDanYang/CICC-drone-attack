# Stage B variance tables

Core trials: 45; extra controlled trials: 10.

| Color | n | All centre_pct values | Median | Worst | Threshold | Median pass | Worst >=30 |
|---|---:|---|---:|---:|---:|---|---|
| red | 15 | [None, 87.1, 87.2, 87.2, None, 83.9, 87.2, 83.9, None, 83.9, None, 87.2, 87.2, None, 82.3] | 87.15 | 82.3 | 68.0 | True | True |
| purple | 15 | [40.4, 70.6, 65.2, 71.0, 44.7, 69.0, 71.4, 44.7, 72.5, 48.9, 69.8, 72.5, 46.8, 68.1, 73.8] | 69.0 | 40.4 | 51.0 | True | True |
| blue | 15 | [75.0, 59.3, 78.8, 81.2, 59.3, 76.9, 76.9, 76.6, 59.3, 59.3, 78.8, 78.1, 78.8, 59.3, 75.0] | 76.6 | 59.3 | 62.0 | True | True |

## Per-run values

- `01_r1_red_baseline`: [] (spread=None pp; pass=False)
- `04_r1_purple_baseline`: [40.4, 44.7, 44.7, 48.9, 46.8] (spread=8.5 pp; pass=True)
- `05_r1_blue_baseline`: [75.0, 81.2, 76.6, 78.1, 75.0] (spread=6.2 pp; pass=True)
- `08_r2_red_baseline`: [87.1, 83.9, 83.9, 83.9, 82.3] (spread=4.8 pp; pass=True)
- `09_r2_purple_baseline`: [70.6, 69.0, 71.4, 69.8, 73.8] (spread=4.8 pp; pass=True)
- `12_r2_blue_baseline`: [59.3, 59.3, 59.3, 59.3, 59.3] (spread=0.0 pp; pass=True)
- `13_r3_red_baseline`: [87.2, 87.2, 87.2, 87.2, 87.2] (spread=0.0 pp; pass=True)
- `16_r3_purple_baseline`: [65.2, 71.0, 72.5, 72.5, 68.1] (spread=7.3 pp; pass=True)
- `17_r3_blue_baseline`: [78.8, 76.9, 76.9, 78.8, 78.8] (spread=1.9 pp; pass=True)

## Order comparison

- `01_r1_red_baseline` canonical=None; shuffled=[None, None, None, None]; delta=[None, None, None, None]
- `04_r1_purple_baseline` canonical=40.4; shuffled=[44.7, 44.7, 48.9, 46.8]; delta=[4.3, 4.3, 8.5, 6.4]
- `05_r1_blue_baseline` canonical=75.0; shuffled=[81.2, 76.6, 78.1, 75.0]; delta=[6.2, 1.6, 3.1, 0.0]
- `08_r2_red_baseline` canonical=87.1; shuffled=[83.9, 83.9, 83.9, 82.3]; delta=[-3.2, -3.2, -3.2, -4.8]
- `09_r2_purple_baseline` canonical=70.6; shuffled=[69.0, 71.4, 69.8, 73.8]; delta=[-1.6, 0.8, -0.8, 3.2]
- `12_r2_blue_baseline` canonical=59.3; shuffled=[59.3, 59.3, 59.3, 59.3]; delta=[0.0, 0.0, 0.0, 0.0]
- `13_r3_red_baseline` canonical=87.2; shuffled=[87.2, 87.2, 87.2, 87.2]; delta=[0.0, 0.0, 0.0, 0.0]
- `16_r3_purple_baseline` canonical=65.2; shuffled=[71.0, 72.5, 72.5, 68.1]; delta=[5.8, 7.3, 7.3, 2.9]
- `17_r3_blue_baseline` canonical=78.8; shuffled=[76.9, 76.9, 78.8, 78.8]; delta=[-1.9, -1.9, 0.0, 0.0]

## GPU timing

