# AgriSense Phase 4 results

Generated 2026-11-18 13:21. All numbers are measured on simulation seeds that were never used for training or tuning.

## Sensor anomaly detection

Test set: 196.8 healthy channel-days plus injected faults. ML alarms are debounced: a sensor must be flagged in 5 of the last 10 minutes.

| Detector | Precision | Recall | F1 | Faults detected | False alarms per channel-day |
|---|---|---|---|---|---|
| rules | 86 % | 53 % | 0.66 | 74 % | 1.18 |
| isolation | 62 % | 48 % | 0.54 | 78 % | 1.13 |
| virtual | 57 % | 66 % | 0.61 | 93 % | 0.33 |
| supervised | 90 % | 84 % | 0.87 | 100 % | 0.17 |

Faults detected (share of fault events flagged at least once) and median delay:

| Fault | rules | isolation | virtual | supervised |
|---|---|---|---|---|
| stuck | 26/26, 10 min | 14/26, 38 min | 26/26, 24 min | 26/26, 7 min |
| spike | 20/20, 2 min | 16/20, 56 min | 15/20, 58 min | 20/20, 7 min |
| drift | 5/15, 137 min | 13/15, 54 min | 14/15, 41 min | 15/15, 54 min |
| offset | 10/22, 0 min | 22/22, 4 min | 22/22, 4 min | 22/22, 4 min |
| dropout | 7/7, 0 min | 0/7 | 7/7, 25 min | 7/7, 9 min |

## Predictive irrigation

Hours until the next irrigation starts, 53,141 test minutes.

| Horizon | Minutes | Model MAE (h) | Straight-line MAE (h) |
|---|---|---|---|
| all | 53,141 | 3.25 | 19.08 |
| 0-6 h | 7,180 | 2.76 | 10.68 |
| 6-24 h | 21,600 | 2.72 | 27.83 |
| 24-48 h | 24,361 | 3.87 | 13.79 |

"Irrigation within 6 h" as a yes/no prediction:

| | Precision | Recall |
|---|---|---|
| Model | 92 % | 69 % |
| Straight line | 76 % | 54 % |

## Controller setpoint optimisation

31 settings searched; the chosen one validated on seeds [600, 601, 602] (3 days each).

| Metric | Default | Tuned | Change |
|---|---|---|---|
| Equipment energy (kWh) | 26.1 | 21.5 | -17.6 % |
| Hours outside temperature targets | 199.2 | 199.0 | -0.1 % |
| Hours outside humidity targets | 145.8 | 150.3 | +3.1 % |
| Water used (L) | 873.8 | 875.7 | +0.2 % |

Tuned parameters (see `optimized_control.yaml`):

| Parameter | Default | Tuned |
|---|---|---|
| `climate.stage1_level` | 0.5 | 0.46 |
| `climate.stage2_offset_c` | 2 | 2.46 |
| `climate.temp_band_c` | 1.5 | 2.76 |
| `climate.vent_benefit_on_c` | 1 | 2.37 |
| `climate.vent_benefit_off_night_c` | 0.3 | 0.42 |
| `climate.mist_cooling_offset_c` | 2 | 2.21 |
| `climate.humidity_band_pct` | 5 | 5.25 |
