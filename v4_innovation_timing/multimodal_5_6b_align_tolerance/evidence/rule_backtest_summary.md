# Red/purple near-contact rule backtest

Sources are archived rosout and frame/actor evidence from the 3.3 sealed comparisons; no code or runtime was changed. The proposed rule is `max_area_ratio >= 0.30`, `last_ratio >= 0.04`, and `lost_seconds <= 1.25` (640x480, area percentages below are VisualServo log values).

|case|color|ALIGN events|max APPROACH area|first qualifying loss|last area|observed gap|tracking resumed|
|---|---:|---:|---:|---|---:|---:|---|
|r1_purple_a1|purple|1|10.2|||||
|r1_red_a1|red|0|None|||||
|r2_purple_a1|purple|3|13.0|||||
|r2_red_a1|red|1|9.1|||||
|r1_purple_a1|purple|1|38.7|2026-10-15T16:32:38.881+00:00|38.7|0.193|False|
|r1_red_a1|red|2|31.6|2026-10-15T16:26:21.892+00:00|31.6|0.01|False|
|r1_purple_a1|purple|1|22.2|||||
|r1_red_a1|red|0|None|||||
|r2_purple_a1|purple|1|6.1|||||
|r2_red_a1|red|0|None|||||
|r3_purple_a1|purple|1|35.5|2026-10-15T17:54:46.395+00:00|35.5|0.051|False|
|r3_red_a1|red|0|None|||||

The archived logs contain no case in which a qualifying loss was followed by a resumed tracker stream. The qualifying losses are terminal loss windows in the archived run; actor-removal evidence is retained in the corresponding `judgement.json` files. This is a clean backtest for the specific false-trigger pattern, but it is not a proof of future safety.
