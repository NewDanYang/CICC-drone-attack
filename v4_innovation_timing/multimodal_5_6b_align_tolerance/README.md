# multimodal_5_6b_align_tolerance

This directory records the two permitted visual-servo tolerance trials and the red/purple loss-rule backtest from `docs/astra-handoff-fm9g-visualservo-tolerance.md`.

The 20/20 red and 30/30 purple trials both stopped before VisualServo at the shared pre-balloon target `(4.3, 1.0, 0.7)`. Neither produced a `Visual Servo Started`, `Aligned!`, or `SPRINT_START` event, so the tolerance hypothesis was not observed. The server was restored to the frozen source and plugin hashes after both trials. The red/purple near-contact completion rule remains undeployed because historical evidence shows premature-completion risk.
