# 第 5 局（v6.4）审计统计

audit dir: /home/ubuntu/tcei_baseline_tools/results/multimodal_v2/20261102T043120_301c41

kinds:
  publish 501, window_frame 49, model_source 97, presence_model_call 114,
  decision 96, v6_no_measure 61, presence_sweep 56, v6_measure 35,
  v6_focal 8, v6_residual 32, v6_principal 18, v6_range 5, inference_error 1,
  gate 2, ready 1, camera_contract 1, processor_input 2, presence_warmup 1,
  mission_result 1, closed 1

modes {'acquire': 58, 'track': 38}; guard {None: 345, 'hold': 156}; publish with bbox 156/501

top published areas:
  0.0503 04:32:48.81 hold [382.7,148.1,515.7,264.3]
  0.0503 04:32:48.53 hold [183.8,141.5,316.8,257.8]
  0.0503 04:32:48.65 hold [263.5,141.4,396.5,257.6]
  0.0503 04:32:48.57 hold [209.2,141.4,342.2,257.7]
  0.0503 04:32:48.75 hold [333.4,143.3,466.4,259.5]
  0.0427 04:32:48.14 hold [135.2,168.2,231.2,305.0]
  0.0425 04:33:22.27 hold [281.7,121.7,366.8,274.9]

注：五条 0.0503 的框 y 区间完全相同、x 中心从 183 扫到 449，
说明它们是**同一测量的连续外推**，不是五次独立测量。
