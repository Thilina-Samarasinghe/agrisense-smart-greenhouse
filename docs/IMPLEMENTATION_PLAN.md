# AgriSense — Implementation Plan

## Guiding decisions

| Decision | Choice | Reason |
|---|---|---|
| Simulation style | Fixed-step time loop (1 s sim sub-steps), NumPy — no SimPy | Greenhouse climate is continuous, not discrete-event |
| Realism | Physics-based lumped model + real-hardware sensor models | Future hardware drops in without changing control logic |
| State separation | True state (physics) ≠ measured state (sensors) | Controller sees only imperfect readings, as in reality |
| Clock | Simulated clock with speed multiplier | Demo a day in minutes; generate ML data quickly |
| Determinism | Seeded RNG | Reproducible scenario tests |
| Database | SQLite via SQLAlchemy → PostgreSQL/TimescaleDB in Phase 5 | Zero setup now; URL change later |
| Persistence rate | Readings stored per sim-minute; all events stored | Avoid millions of rows at high speed |
| Hardware link | Device driver interfaces + MQTT-shaped internal bus | MQTT adapter is a drop-in later |
| Zones | 3 by default (Tomato, Chilli, Lettuce), N via config | |

## Phase 0 — Foundation (1–2 days)
- Monorepo layout, `.gitignore`, `.editorconfig`
- Backend: `pyproject.toml`, FastAPI app with `/api/health`, settings, pytest, Ruff
- Frontend: Next.js + TypeScript + Tailwind, API-status page, Recharts dependency
- README and this plan

## Phase 1 — Simulation engine (1.5–2 weeks)
1. `sim/clock.py` — simulated time, speed multiplier, sub-stepping
2. `sim/weather.py` — solar geometry, clear-sky radiation, cloud, outside T/RH diurnal cycle, rain
3. `sim/physics.py` — air energy balance, vapour balance (Tetens, VPD, condensation), CO₂ balance,
   Penman-Monteith/Stanghellini transpiration, FAO-56 soil water balance, PAR/DLI/lux
4. `sim/zone.py` — zone state + crop profile + equipment
5. `devices/interfaces.py` — `SensorDriver`, `ActuatorDriver`, `Reading`, `Command`
6. `devices/sensors.py` — SHT31, capacitive soil, BH1750, SCD30, JSN-SR04T, YF-S201 models
   (lag, noise, quantisation, drift, saturation, faults)
7. `devices/actuators.py` — pump, valve, fan, LED lights with real specs, energy & water metering
8. `profiles/*.yaml` + Pydantic validation — greenhouse, crops, sensors
9. CLI: run a simulated day → CSV
10. Tests: physical plausibility, mass conservation, determinism

## Phase 2 — Automation engine (1 week)
- Rule engine with priority layers: emergency stop → interlocks → manual override → rules → schedules
- Hysteresis, minimum on/off times, max run time
- Sensor fault detection (stale, out-of-range, rate-of-change) → fail-safe
- Decision log with explanations
- Scenario tests: hot day, rainfall, water shortage, sensor failure, pump failure

## Phase 3 — API, storage & dashboard (1.5–2 weeks)
- Engine runner as FastAPI background task; WebSocket snapshot stream (UI throttled to 1–2 Hz)
- REST: zones, actuators, modes/overrides, rules, scenarios, reports
- SQLAlchemy models + Alembic: readings, events, actuator log, alerts, calibration
- Dashboard pages: overview, zone detail, scenarios, analytics, rules, events

## Phase 4 — Intelligence (1–2 weeks)
- Anomaly detection (rolling z-score → IsolationForest), precision/recall vs. injected faults
- Predictive irrigation (time-to-threshold forecast; linear baseline vs. gradient boosting)
- Optimisation: irrigation timing and time-of-use tariff; water/kWh vs. baseline over a simulated week
- Crop advisor (rule-based, optional LLM summary)

## Phase 5 — Deployment & polish (3–5 days)
- Dockerfiles, docker-compose (API, frontend, PostgreSQL/TimescaleDB, optional Mosquitto)
- GitHub Actions CI (pytest, Ruff, ESLint, build)
- Architecture docs, demo GIF

## Phase 6 — Real hardware
- ESP32 firmware (sensors → MQTT, actuator commands with TTL fail-safe)
- `MqttSensorDriver` / `MqttActuatorDriver`, per-device `source: sim | mqtt`
- Calibration workflow; shadow-mode twin parameter fitting (SciPy least squares)

## Risks
- Unrealistic constants → validate against published greenhouse behaviour in tests
- Phase 4 scope creep → Phases 1–3 are a complete project on their own
- WebSocket flooding at high sim speeds → throttle UI updates
