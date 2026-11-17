# 🌱 AgriSense — Smart Greenhouse Simulation & Automation Platform

> A software-based smart greenhouse platform featuring physics-based virtual sensor simulation,
> automated irrigation, climate control, environmental analytics and AI-driven agricultural optimisation.
> Built **hardware-independent today, hardware-ready for tomorrow.**

**Status:** Phase 0 — project foundation (see [Roadmap](#-roadmap))

---

## Table of contents

1. [What is AgriSense?](#-what-is-agrisense)
2. [Why simulation first?](#-why-simulation-first)
3. [Key features](#-key-features)
4. [How it works — architecture](#-how-it-works--architecture)
5. [The physics model](#-the-physics-model)
6. [Automation & control logic](#-automation--control-logic)
7. [Greenhouse zones & crop profiles](#-greenhouse-zones--crop-profiles)
8. [Technology stack](#-technology-stack)
9. [Project structure](#-project-structure)
10. [Getting started](#-getting-started)
11. [Roadmap](#-roadmap)
12. [Future hardware — sensors, actuators & controllers](#-future-hardware--sensors-actuators--controllers)
13. [Moving from simulation to real hardware](#-moving-from-simulation-to-real-hardware)
14. [Safety notes](#-safety-notes)

---

## 🌿 What is AgriSense?

AgriSense is a **digital greenhouse**. It simulates a real greenhouse with several growing
zones, each with its own crop, microclimate, irrigation and equipment. An automation engine watches
the (simulated) sensors and controls (virtual) fans, pumps, valves and grow lights, exactly as a real
greenhouse controller would. A web dashboard shows everything live and lets you trigger scenarios
such as a heatwave, rainfall, a water shortage or a broken sensor, and watch the system react.

Default greenhouse layout:

| Zone | Crop | Character |
|---|---|---|
| **Zone A** | 🍅 Tomato | Warm-season, high water demand, tall canopy |
| **Zone B** | 🌶️ Chilli | Warm-season, moderate water, drought-tolerant |
| **Zone C** | 🥬 Lettuce | Cool-season, shallow roots, sensitive to heat |

The number of zones and their crops are configuration, not code — the engine supports any number.

It is **not** a dashboard of random numbers. The readings come from a physics model of heat, water
vapour, CO₂, light and soil water, so the system behaves like a real one: it heats up at midday,
humidity rises at night, soil dries faster on hot sunny days, and ventilation actually cools.

## 🤔 Why simulation first?

- **No hardware cost or risk** while the software is designed and tested.
- **Reproducible experiments** — a seeded simulation gives the same result every time, so the
  automation logic can be covered by automated tests ("hot day → fan ON within 2 minutes").
- **Time acceleration** — run a full 24-hour day in minutes, or generate weeks of training data for
  the ML features.
- **Safe failure testing** — break sensors, drain the tank or simulate a heatwave without killing plants.
- **Hardware-ready design** — the simulator talks through the same device interfaces and message
  format that real ESP32 sensors will use. Connecting hardware later means swapping a *driver*, not
  rewriting the platform.

## ✨ Key features

**Virtual environmental monitoring** (per zone)
- Air temperature (°C), relative humidity (%), vapour pressure deficit (kPa)
- Soil volumetric water content (%) and soil temperature
- Light — PAR (µmol/m²/s), daily light integral (mol/m²/day) and lux
- CO₂ concentration (ppm)
- Water tank level (%, litres) and irrigation flow (L/min)
- Configurable sampling interval (e.g. every 5 s)

**Automation engine**
- Ventilation on high temperature / humidity, off when back in range
- Irrigation when soil moisture falls below threshold, stop at target
- Pump lock-out and alert when the water tank is critically low
- Grow lights when natural light (DLI) is insufficient
- **Hysteresis** and minimum on/off times to prevent rapid switching
- Operating modes: **AUTO / MANUAL / OFF**, timed manual override, **emergency stop**
- Every decision is logged with the rule and the readings that caused it

**Scenario controls**
- Hot day · heatwave · rainfall · cloudy week · cold night
- Reduce soil moisture · water shortage · pump failure
- Sensor failures: stuck value, dropout, spikes, drift
- Sudden humidity change

**Analytics**
- Daily temperature / humidity trends, soil moisture history
- Water consumption, irrigation duration, energy use (kWh) per device
- Equipment activation history and threshold violations
- Zone-by-zone comparison

**Intelligence (later phases)**
- Anomaly detection (sensor faults) evaluated against injected, labelled faults
- Predictive irrigation (time-to-threshold forecasting)
- Water & energy optimisation (irrigate in cooler hours, time-of-use tariffs)
- Crop advisor recommendations
- Digital-twin calibration against real sensor data

## 🏗️ How it works — architecture

```
 ┌────────────────────────────────────────────────────────────────────────────┐
 │                         SIMULATION ENGINE (Python)                         │
 │  Weather & sun ─► Physics per zone (energy, vapour, CO₂, soil water, light) │
 │                     ▲ actuator effects                │ true state          │
 └─────────────────────┼─────────────────────────────────┼─────────────────────┘
                       │                                 ▼
 ┌─────────────────────┴─────────────────────────────────────────────────────┐
 │                               DEVICE LAYER                                │
 │  SimActuatorDriver   ◄── commands      SimSensorDriver (noise, lag, faults)│
 │  MqttActuatorDriver  (future ESP32)    MqttSensorDriver (future ESP32)     │
 └─────────────────────┬─────────────────────────────────┬────────────────────┘
                       │  in-process message bus (MQTT-compatible topics)     
 ┌─────────────────────┴─────────────────────────────────┴────────────────────┐
 │  AUTOMATION ENGINE: interlocks ► overrides ► rules (hysteresis) ► schedules │
 └─────────────────────┬──────────────────────────────────────────────────────┘
                       ▼
 ┌────────────────────────────────────────────────────────────────────────────┐
 │  FastAPI backend: REST API · WebSocket live telemetry · SQLAlchemy storage │
 └─────────────────────┬──────────────────────────────────────────────────────┘
                       ▼
 ┌────────────────────────────────────────────────────────────────────────────┐
 │  Next.js dashboard: live zones · charts · controls · scenarios · alerts    │
 └────────────────────────────────────────────────────────────────────────────┘
```

Important design principles:

1. **True state vs. measured state.** Physics computes the *true* climate. Sensors then add the
   imperfections of real hardware (noise, lag, resolution, drift, saturation, faults). The automation
   engine only ever sees sensor readings — just like a real controller.
2. **Pure core.** `agrisense_core` (physics, devices, control) has no web dependencies; it is fully
   unit-testable and could run on a Raspberry Pi gateway.
3. **Simulated clock** with a speed multiplier (1×, 60×, 600×). Physics integrates in fixed 1-second
   sub-steps for numerical stability regardless of speed.
4. **SI units internally**, conversions only at the edges (UI, sensor raw values).

## 🔬 The physics model

Each zone is modelled as a well-mixed "lumped" volume of air, soil and crop, using established
greenhouse-climate and FAO-56 crop-water equations.

| Sub-model | What it computes | Main drivers |
|---|---|---|
| **Weather & sun** | Outside temperature, humidity, wind, rain, solar radiation | Latitude, day of year, time, cloud cover (later: real weather data) |
| **Air energy balance** | Inside air temperature | Solar gain through cover, cover heat loss (U-value), ventilation, transpiration cooling, heater/lamps |
| **Vapour balance** | Humidity, VPD, condensation | Transpiration, misting, ventilation, cold-cover condensation (Tetens equation) |
| **Transpiration** | Crop water use | Penman-Monteith / Stanghellini — radiation, VPD, leaf area index, water stress |
| **Soil water** | Volumetric water content | Irrigation, rain, evapotranspiration, drainage above field capacity |
| **CO₂ balance** | CO₂ ppm | Photosynthesis (light-response curve), respiration, ventilation, dosing |
| **Light** | PAR, DLI, lux | Sun, cloud, cover transmission, shade screen, LED grow lights |
| **Actuators** | Flows, power, energy, water | Real specs: L/h per emitter, m³/h per fan, watts, start-up delay, failures |

Simplified air energy balance:

```
ρ·cp·V · dT/dt = τ·A·I_solar − U·A_cover·(T_in − T_out) − ρ·cp·Q_vent·(T_in − T_out)
                 − λ·E_transpiration + Q_heater + Q_lamps
```

Soil water balance (FAO-56 style):

```
dθ/dt = (irrigation + rain − ET·Ks − drainage) / root_depth
```

The model is validated by tests against known greenhouse behaviour, e.g. a closed greenhouse at
sunny midday reaches 10–20 °C above outside; with fans (40–60 air changes/hour) it stays 2–5 °C above
outside; lettuce uses ≈2–4 mm/day of water and greenhouse tomato ≈3–6 mm/day in summer; water mass
is conserved (tank out = soil in + drainage).

Default greenhouse (configurable): latitude 6.9° N, each zone 10 m × 5 m with 3 m gutter height,
polyethylene cover.

## ⚙️ Automation & control logic

Decisions are evaluated in strict priority order:

| Priority | Layer | Example |
|---|---|---|
| 1 | **Emergency stop** | All actuators OFF and latched until manually reset |
| 2 | **Safety interlocks** | Tank < 10 % → pump locked out; pump max run time; failed sensor → fail-safe |
| 3 | **Manual override** | User forces fan ON for 30 min, then automatically returns to AUTO |
| 4 | **Automatic rules** | Hysteresis bands: fan ON at 28 °C, OFF at 26 °C |
| 5 | **Schedules** | Grow lights allowed 06:00–20:00 when DLI target not reached |

Example rules (per-crop thresholds come from crop profiles):

| Condition | Action |
|---|---|
| Temperature above upper limit | Ventilation ON |
| Temperature back below (limit − hysteresis) | Ventilation OFF |
| Soil moisture below threshold | Open zone valve + start pump |
| Soil moisture reaches target | Stop irrigation |
| Tank critically low | Disable irrigation, raise CRITICAL alert |
| Light / DLI insufficient | Grow lights ON |
| Sensor stale / out of range | Mark sensor FAULT, loop goes to fail-safe, raise alert |

Every action is logged with an explanation, e.g.
`Zone A · Fan ON · rule CLIMATE_HIGH_T · temp 29.4 °C > 28.0 °C`.

## 🌾 Greenhouse zones & crop profiles

Thresholds are crop-specific (and growth-stage specific) rather than one set for every plant.
Indicative day-time targets used as defaults:

| Crop | Air temp | RH | Soil VWC | DLI |
|---|---|---|---|---|
| Tomato | 21–27 °C | 60–80 % | 25–35 % | 20–30 mol/m²/day |
| Chilli | 21–29 °C | 60–75 % | 22–32 % | 18–25 mol/m²/day |
| Lettuce | 15–21 °C | 60–75 % | 28–38 % | 12–17 mol/m²/day |

Profiles live in YAML (`backend/agrisense_core/profiles/`) and can be edited without code changes.

## 🧰 Technology stack

| Layer | Technology |
|---|---|
| Simulation & control | Python 3.12, NumPy, Pydantic, (SciPy for model calibration) |
| Backend API | FastAPI, Uvicorn, WebSockets, SQLAlchemy, Alembic |
| Database | SQLite (development) → PostgreSQL / TimescaleDB (deployment) |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS, Recharts |
| Machine learning | scikit-learn (anomaly detection, forecasting) |
| Quality | pytest, Ruff, ESLint, GitHub Actions |
| Deployment | Docker, Docker Compose |
| Future hardware link | MQTT (Mosquitto), ESP32 firmware |

## 📁 Project structure

```
agrisense-smart-greenhouse/
├── backend/
│   ├── agrisense_core/        # pure Python, no web framework
│   │   ├── sim/               # clock, weather, physics, zones, scenarios
│   │   ├── devices/           # driver interfaces, simulated sensors & actuators
│   │   ├── control/           # rule engine, hysteresis, interlocks, modes
│   │   └── profiles/          # crop / greenhouse / sensor YAML configs
│   ├── app/                   # FastAPI application
│   │   ├── api/               # REST routes
│   │   ├── ws/                # WebSocket live telemetry
│   │   ├── db/                # SQLAlchemy models & migrations
│   │   ├── services/          # engine runner, persistence, analytics
│   │   ├── config.py
│   │   └── main.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/                  # Next.js dashboard
│   ├── app/
│   ├── components/
│   └── lib/
├── ml/                        # Phase 4 experiments & models
├── infrastructure/            # Docker / compose / CI (Phase 5)
├── docs/                      # implementation plan, design notes
└── README.md
```

## 🚀 Getting started

### Prerequisites
- Python 3.12+
- Node.js 20+ and npm
- (Later) Docker Desktop

### Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload            # http://localhost:8000/docs
pytest                                   # run tests
ruff check . && ruff format --check .    # lint
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                              # http://localhost:3000
```

The home page shows whether the backend is reachable.

## 🗺️ Roadmap

| Phase | Goal | Done when |
|---|---|---|
| **0 — Foundation** ✅ in progress | Repo structure, tooling, backend & frontend skeletons, docs | Health endpoint + tests + lint pass; dashboard shows API status |
| **1 — Simulation engine** | Weather, physics per zone, actuator specs, sensor hardware models, device interfaces | A simulated 24 h day is physically plausible, deterministic with a seed, validated by tests |
| **2 — Automation engine** | Rules, hysteresis, interlocks, modes, override, emergency stop, fault detection | Every scenario (hot day, water shortage, sensor failure …) passes as an automated test |
| **3 — API, storage & dashboard** | REST + WebSocket, database, live dashboard, scenario panel, analytics | Click "Simulate hot day" and watch the fan react live with an explained log entry |
| **4 — Intelligence** | Anomaly detection, predictive irrigation, optimisation, crop advisor | Measured water/energy savings vs. rule-based control over a simulated week |
| **5 — Deployment & polish** | Docker Compose, PostgreSQL/TimescaleDB, CI, docs, demo | `docker compose up` runs the whole platform |
| **6 — Real hardware** | ESP32 firmware, MQTT drivers, calibration, shadow-mode digital twin | Real sensors feed the same dashboard; twin parameters fitted to real data |

Detailed plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

---

## 🔌 Future hardware — sensors, actuators & controllers

None of this is needed now. Every simulated sensor is modelled on a specific real part below, so
the software already expects that part's accuracy, range, raw output and failure modes.

### Controllers & communication

| Item | Recommended part | Qty | Purpose |
|---|---|---|---|
| Zone controller | **ESP32-WROOM-32 DevKit** or **ESP32-S3 DevKit** | 1 per zone (3) | Reads zone sensors, drives zone valve/fan/lights, Wi-Fi + MQTT |
| Gateway / server | **Raspberry Pi 4 or 5** (4 GB+) — or a laptop | 1 | Runs Mosquitto MQTT broker, AgriSense backend, database, dashboard |
| MQTT broker | **Eclipse Mosquitto** (software) | 1 | Message bus between ESP32s and backend |
| Long-distance bus (optional) | **MAX485 RS-485 module** | as needed | For industrial sensors or cable runs longer than a few metres |

### Sensors (per zone unless stated)

| Measurement | Recommended sensor | Interface | Key specs (what the simulator models) | Qty |
|---|---|---|---|---|
| Air temperature & humidity | **Sensirion SHT31** (or SHT40) in a radiation shield. Budget: DHT22 | I²C | ±0.3 °C, ±2 % RH, 0.1 resolution, ~8 s response | 1 per zone + 1 outside |
| Soil moisture | **Capacitive soil moisture sensor v1.2** (corrosion-resistant). Pro: RS-485 soil sensor (moisture + temperature + EC) | Analog (ESP32 ADC) / RS-485 | Raw 0–4095 counts, needs dry/wet calibration, temperature drift | 2 per zone |
| Soil temperature | **DS18B20 waterproof probe** | 1-Wire | ±0.5 °C | 1 per zone |
| Light | **BH1750** lux sensor (saturates at 65,535 lux in strong sun). Better: **TSL2591** (to ~88,000 lux). Pro: PAR quantum sensor | I²C / analog | Range, resolution, saturation; converted to PAR & DLI | 1 per zone |
| CO₂ | **Sensirion SCD30 / SCD40** (NDIR, also gives T/RH). Budget: MH-Z19B | I²C / UART | ±(30–50 ppm + 3 %), warm-up time, 2 s sampling | 1 per zone (or 1 shared) |
| Water tank level | **JSN-SR04T waterproof ultrasonic** + backup **float switch** for low level | GPIO / digital | Distance → level via tank geometry; occasional echo dropouts | 1 per tank |
| Irrigation flow | **YF-S201 hall-effect flow meter** | Pulse (GPIO interrupt) | ~450 pulses/L; confirms the pump is really delivering water | 1 per irrigation line |
| Pump/fan feedback (optional) | **INA219** or **ACS712** current sensor | I²C / analog | Detects a running-but-failed or stalled device | per actuator |
| Outside weather (optional) | BME280 + rain sensor + anemometer | I²C / digital | Feeds the weather model with real data | 1 |

### Actuators

| Equipment | Recommended part | Driven by | Notes |
|---|---|---|---|
| Irrigation pump | **12 V DC diaphragm pump** (or submersible pump) | Relay / logic-level MOSFET | Spec flow (L/min) & power (W) are entered in `greenhouse.yaml` |
| Zone valves | **12 V normally-closed solenoid valve** | Relay / MOSFET + flyback diode | One per zone so zones irrigate independently; fails closed |
| Drip irrigation | Drip line / emitters (e.g. 2 L/h), filter, tubing | — | Emitter count × flow is used by the soil-water model |
| Ventilation fans | **12 V DC exhaust fans** (PWM capable) or AC fans | MOSFET (PWM) / SSR | Airflow (m³/h) defines the ventilation rate in the model |
| Grow lights | **Full-spectrum LED grow lights** | Relay / SSR | PPFD and wattage used for light and energy models |
| Vents / shade (optional) | Servo or 12 V linear actuator; shade screen motor | Motor driver (e.g. BTS7960) | Natural ventilation & shading |
| Misting / heating (optional) | Misting nozzles + pump; heater | Relay / SSR | Humidity raise / frost protection |
| Switching | **4- or 8-channel opto-isolated relay module**, or **IRLZ44N** logic-level MOSFETs, **SSR** for AC loads | ESP32 GPIO | Use flyback diodes on all inductive DC loads |

### Power & installation

| Item | Purpose |
|---|---|
| 12 V DC power supply (sized for pump + fans + valves + margin) | Main DC power |
| 12 V → 5 V buck converter (e.g. LM2596 / MP1584) | Powers ESP32 & sensors |
| Inline fuses / fuse block | Short-circuit protection per circuit |
| IP65 enclosures + cable glands | Moisture protection for electronics |
| Sensor radiation shield | Accurate air temperature in sunlight |
| RCD/GFCI-protected outlet | Mandatory for any mains equipment near water |
| Wires, terminal blocks, connectors, heat-shrink | Wiring |

### Starter kit vs. full build

- **Starter (one zone, proof of concept):** 1 × ESP32, 1 × SHT31, 2 × capacitive soil sensors,
  1 × BH1750, 1 × 4-ch relay, 1 × 12 V pump, 1 × solenoid valve, 1 × 12 V fan, 12 V PSU + buck converter.
  The other zones stay simulated (hybrid mode).
- **Full build (three zones):** everything in the tables above, plus SCD30/SCD40 CO₂, tank level,
  flow meter, grow lights and a Raspberry Pi gateway.

## 🔄 Moving from simulation to real hardware

Because the software is designed around a device layer, connecting hardware is incremental:

1. **Same message format.** Internally AgriSense already uses MQTT-style topics:
   ```
   agrisense/{greenhouse}/{zone}/sensor/{sensor_id}        → {"raw": 2310, "value": 31.4, "unit": "%", "quality": "ok", "ts": "..."}
   agrisense/{greenhouse}/{zone}/actuator/{actuator_id}/set ← {"state": "on", "reason": "SOIL_LOW", "ttl_s": 600}
   agrisense/{greenhouse}/{zone}/actuator/{actuator_id}/state → {"state": "on", "confirmed": true}
   ```
   ESP32 firmware publishes and subscribes to exactly these topics.
2. **Per-device source switch.** In `sensors.yaml` each device is `source: sim` or `source: mqtt`.
   You can connect a single real sensor while the rest stays simulated (hardware-in-the-loop).
3. **Calibration** is stored per sensor (e.g. capacitive soil sensor: raw count in dry air and in
   water → VWC curve), so raw readings convert to the same units the simulator uses.
4. **Command confirmation.** Actuator commands are confirmed by feedback (flow meter, current
   sensor). A pump that runs but delivers no water triggers an alert — tested in simulation first.
5. **Shadow-mode digital twin.** With real sensors connected, the simulator runs in parallel using
   the same actuator states. Differences between predicted and measured values are used to fit the
   model parameters (cover U-value, transmission, ventilation rate) so the twin matches *your*
   greenhouse and can be used for prediction and optimisation.
6. **Fail-safe firmware.** ESP32s turn actuators off if they lose contact with the server
   (`ttl_s` in each command), and the float switch hard-wires a pump cut-off independent of software.

## ⚠️ Safety notes

- Work with **12 V DC** wherever possible. Any **mains (AC) wiring** — pumps, heaters, large fans,
  grow lights — must use certified SSRs/contactors, an RCD/GFCI, proper enclosures and should be
  installed or checked by a qualified electrician.
- Keep electronics in sealed enclosures away from irrigation water.
- Software interlocks are not a substitute for hardware protection: use fuses, a float switch for
  dry-run protection and normally-closed valves that fail safe.

---

*AgriSense is a learning and portfolio project. Crop thresholds are indicative defaults — check
local agricultural guidance for your crop variety and climate.*
