# Retry formal test — red

- run_id: `20261001T171326_2aff15`
- official natural-language entry: `mission_once.py`
- total_time: `59.484 s`
- mission_success: `false`
- bt_success: `false`
- end_status: `completed`
- takeoff: success
- cross_frame: success
- detect_aruco: incomplete
- return_cross_frame / hit_balloon / land: not reached
- safety boundary: not triggered
- failure reason: `/mission_result=FAILURE` after the ArUco detector reached its 20 s timeout without detecting a marker.

The JSONL shows the ArUco detector was enabled for this mission, then timed out and disabled. This retry did not reproduce the V1 safety-boundary event.
