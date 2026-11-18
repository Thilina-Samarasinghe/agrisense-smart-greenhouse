# AgriSense: Implementation Plan

## Guiding decisions

| Decision | Choice | Reason |
|---|---|---|
| Simulation style | Fixed-step time loop (1 s sim sub-steps), NumPy (no SimPy) | Greenhouse climate is continuous, not discrete-event |
| Realism | Physics-based lumped model + real-hardware sensor models | Future hardware drops in without changing control logic |
| State separation | True state (physics) ≠ measured state (sensors) | Controller sees only imperfect readings, as in reality |
| Clock | Simulated clock with speed multiplier | Demo a day in minutes; generate ML data quickly |
| Determinism | Seeded RNG | Reproducible scenario tests |
| Database | SQLite via SQLAlchemy → PostgreSQL/TimescaleDB in Phase 5 | Zero setup now; URL change later |
| Persistence rate | Readings stored per sim-minute; all events stored | Avoid millions of rows at high speed |
| Hardware link | Device driver interfaces + MQTT-shaped internal bus | MQTT adapter is a drop-in later |
| Zones | 3 by default (Tomato, Chilli, Lettuce), N via config | |

## Phase 0: Foundation (1–2 days) ✅ done
- Monorepo layout, `.gitignore`, `.editorconfig`
- Backend: `pyproject.toml`, FastAPI app with `/api/health`, settings, pytest, Ruff
- Frontend: Next.js + TypeScript + Tailwind, API-status page, Recharts dependency
- README and this plan

## Phase 1: Simulation engine (1.5–2 weeks) ✅ done
1. `sim/clock.py`: simulated time, speed multiplier, sub-stepping
2. `sim/weather.py`: solar geometry, clear-sky radiation, cloud, outside T/RH diurnal cycle, rain
3. `sim/physics.py`: air energy balance, vapour balance (Tetens, VPD, condensation), CO₂ balance,
   Penman-Monteith/Stanghellini transpiration, FAO-56 soil water balance, PAR/DLI/lux
4. `sim/engine.py`: zones, hydraulics (pump, valves, tank, rain harvesting), sensor sampling;
   `sim/scenarios.py`: weather events, disturbances, faults
5. `devices/interfaces.py`: `SensorDriver`, `ActuatorDriver`, `Reading`, `Command`;
   `devices/bus.py`: in-process MQTT-style bus
6. `devices/sensors.py`: SHT31, capacitive soil, DS18B20, BH1750, SCD30, JSN-SR04T, YF-S201 models
   (lag, noise, quantisation, drift, saturation, faults)
7. `devices/actuators.py`: pump, valve, fan, LED lights with real specs, energy & water metering
8. `profiles/*.yaml` + Pydantic validation: greenhouse, crops, sensors
9. CLI (`agrisense simulate`): run a simulated day → CSV
10. Tests: physical plausibility, mass conservation, determinism (63 tests)

## Phase 2: Automation engine (1 week) ✅ done
1. `control/controller.py`: priority layers (emergency stop → interlocks → operator mode → rules →
   minimum on/off times), zone rules (staged fans, humidity venting, fan-and-fog misting,
   irrigation cycles, DLI grow lights, heating), interlocks (tank lockout, pump no-flow latch,
   pump run limit, unexpected flow, high-temperature emergency), decision log, command TTL
2. `control/health.py`: stale, out-of-range, spike, stuck, saturation, warm-up detection;
   soil probe disagreement; fail-safe behaviour per loop
3. `control/alerts.py`: deduplicated, auto-clearing and latched alerts
4. `control/hysteresis.py`, `control/modes.py`: hysteresis, minimum times, AUTO/MANUAL/OFF, timed overrides
5. `profiles/control.yaml` + `ControlConfig` schema
6. `runtime.py`: closed loop (simulator and controller only connected through the bus)
7. CLI: controller on by default, `--no-control`, `--log`
8. Tests: 33 new unit and closed-loop scenario tests (96 total)
9. Performance: faster reading messages and bus topic matching (about 2.5× faster closed loop)

## Phase 3: API, storage & dashboard (1.5–2 weeks) ✅ done
1. `app/services/simulation.py`: runtime advanced in an asyncio background loop on the event-loop
   thread (all handlers async, no locks), capped steps per slice with a `lagging` flag, speed,
   pause, fast-forward, new runs with pruning
2. `app/db/`: SQLAlchemy 2 models (runs, zone/greenhouse/actuator states, sensor readings,
   decisions, alerts), batched writes per sim-minute (readings every 5 sim-minutes)
3. `app/api/`: REST for state, config, sensors, speed, scenarios, overrides, modes, emergency
   stop, alarm reset, history (auto-bucketed), decisions, alerts, analytics summary, runs
4. `app/ws/live.py`: live state at 2 Hz
5. `app/services/analytics.py`: water, energy, equipment use, time outside crop targets
6. Frontend (Next.js 15.5.29 patched, React 19.1.10, Recharts 3.10.1): overview, zone pages,
   scenarios, analytics, events; validated colour-blind-safe palette, light/dark themes,
   status with icon + label, table views
7. Control fix found on the dashboard: fans no longer run all night without benefit (−20 % energy)
8. 13 API tests (109 total)
9. Deferred to Phase 5: Alembic migrations (with the PostgreSQL move)

## Phase 4: Intelligence (1–2 weeks) ✅ done
1. `intelligence/recorder.py`, `features.py`: per-minute observations (controller view + separate
   truth/labels), vectorised features shared by training and live scoring
2. `intelligence/dataset.py`: closed-loop runs with random labelled sensor faults, parallel, cached;
   separate seeds for training, calibration and test (28 runs, 108 greenhouse-days)
3. `intelligence/anomaly.py`: rules vs IsolationForest vs virtual sensor (analytical redundancy)
   vs supervised classifier; calibrated thresholds, debouncing, fault isolation; event-level
   recall, delays and false alarms per sensor-day
4. `intelligence/forecast.py`: hours to next irrigation, gradient boosting vs straight line
5. `intelligence/optimize.py`: simulation-based setpoint search (31 settings), validated on unseen
   seeds (−17.6 % energy, humidity time-outside-target +3.1 %); not auto-applied.
   Time-of-use tariffs were dropped: pump energy is negligible next to fans, which cannot be shifted
6. `intelligence/advisor.py`: explainable rule-based crop advice (no LLM)
7. `intelligence/pipeline.py` + `agrisense ml all|train|optimize`: reports in `ml/reports/`
8. API `/api/intelligence/*`, live scoring (`intelligence/live.py`), Insights page, forecast on overview
9. PostgreSQL support (tested on Neon): background batched writes with retry, autocommit reads in
   threads, SQL-side aggregation, retention, storage status; `sslnegotiation=direct` workaround

## Phase 5: Deployment & polish (3–5 days)
- Dockerfiles, docker-compose (API, frontend, PostgreSQL/TimescaleDB, optional Mosquitto)
- GitHub Actions CI (pytest, Ruff, ESLint, build)
- Architecture docs, demo GIF

## Phase 6: Real hardware
- ESP32 firmware (sensors → MQTT, actuator commands with TTL fail-safe)
- `MqttSensorDriver` / `MqttActuatorDriver`, per-device `source: sim | mqtt`
- Calibration workflow; shadow-mode twin parameter fitting (SciPy least squares)

## Risks
- Unrealistic constants → validate against published greenhouse behaviour in tests
- Phase 4 scope creep → Phases 1–3 are a complete project on their own
- WebSocket flooding at high sim speeds → throttle UI updates
