# 🌱 AgriSense: Smart Greenhouse Simulation & Automation Platform

> A software-based smart greenhouse platform featuring physics-based virtual sensor simulation,
> automated irrigation, climate control, environmental analytics and AI-driven agricultural optimisation.
> Built **hardware-independent today, hardware-ready for tomorrow.**

**Status:** Phase 1 (physics simulation engine) implemented. Next: Phase 2, the automation engine.
See the [Roadmap](#-roadmap).

---

## Table of contents

1. [What is AgriSense?](#-what-is-agrisense)
2. [Why simulation first?](#-why-simulation-first)
3. [Key features](#-key-features)
4. [How it works: architecture](#-how-it-works-architecture)
5. [The physics model](#-the-physics-model)
6. [Simulated sensors](#-simulated-sensors)
7. [Simulated actuators and hydraulics](#-simulated-actuators-and-hydraulics)
8. [Scenarios](#-scenarios)
9. [Model validation](#-model-validation)
10. [Automation & control logic (Phase 2)](#-automation--control-logic-phase-2)
11. [Greenhouse zones & crop profiles](#-greenhouse-zones--crop-profiles)
12. [Configuration files](#-configuration-files)
13. [Technology stack](#-technology-stack)
14. [Project structure](#-project-structure)
15. [Getting started](#-getting-started)
16. [Roadmap](#-roadmap)
17. [Future hardware: sensors, actuators & controllers](#-future-hardware-sensors-actuators--controllers)
18. [Moving from simulation to real hardware](#-moving-from-simulation-to-real-hardware)
19. [Safety notes](#-safety-notes)

---

## 🌿 What is AgriSense?

AgriSense is a **digital greenhouse**. It simulates a real greenhouse with several growing
zones, each with its own crop, microclimate, irrigation and equipment. An automation engine watches
the (simulated) sensors and controls (virtual) fans, pumps, valves and grow lights, exactly as a real
greenhouse controller would. A web dashboard will show everything live and let you trigger
scenarios such as a heatwave, rainfall, a water shortage or a broken sensor, and watch the system react.

Default greenhouse layout:

| Zone | Crop | Character |
|---|---|---|
| **Zone A** | 🍅 Tomato | Warm-season, high water demand, tall canopy |
| **Zone B** | 🌶️ Chilli | Warm-season, moderate water, drought-tolerant |
| **Zone C** | 🥬 Lettuce | Cool-season, shallow roots, sensitive to heat |

The number of zones and their crops are configuration, not code. The engine supports any number.

It is **not** a dashboard of random numbers. The readings come from a physics model of heat, water
vapour, CO₂, light and soil water, so the system behaves like a real one: it heats up at midday,
humidity rises at night, soil dries faster on hot sunny days, and ventilation actually cools.

## 🤔 Why simulation first?

- **No hardware cost or risk** while the software is designed and tested.
- **Reproducible experiments:** a seeded simulation gives the same result every time, so the
  automation logic can be covered by automated tests ("hot day: fan ON within 2 minutes").
- **Time acceleration:** run a full 24-hour day in seconds, or generate weeks of training data for
  the ML features.
- **Safe failure testing:** break sensors, drain the tank or simulate a heatwave without killing plants.
- **Hardware-ready design:** the simulator talks through the same device interfaces and message
  format that real ESP32 sensors will use. Connecting hardware later means swapping a *driver*, not
  rewriting the platform.

## ✨ Key features

Legend: ✅ implemented, 🔜 planned.

**Physics simulation engine** ✅
- Sun position and solar radiation for any latitude, day and time
- Stochastic but reproducible weather: clouds, wind, rain events, day/night temperature cycle
- Per-zone air temperature, humidity, VPD, CO₂, soil moisture, soil temperature, light (PAR, DLI, lux)
- Crop transpiration and photosynthesis, soil water balance with drainage and water stress
- Simulated clock with speed multiplier (1×, 60×, 600×) and fixed physics sub-steps

**Virtual sensors (modelled on real parts)** ✅
- SHT31 air temperature/humidity, capacitive soil moisture, DS18B20 soil temperature,
  BH1750 light, SCD30 CO₂, JSN-SR04T tank level, YF-S201 flow meter
- Raw outputs, calibration, accuracy, noise, lag, resolution, saturation, warm-up, dropouts
- Fault injection: stuck, dropout, spike, drift, offset

**Virtual actuators** ✅
- Pump, zone valves, PWM fans, LED grow lights, misters, heaters
- Start-up delay, power draw, energy (Wh) and runtime metering, command time-to-live fail-safe
- Faults: failed (runs, no effect), stuck on, stuck off
- Hydraulics: shared pump capacity, per-zone drip emitters, tank, rain-water harvesting

**Scenario controls** ✅
- Hot day, heatwave, rainfall, cloudy, cold night
- Humidity spike, dry soil, water shortage, tank refill
- Pump failure, any actuator fault, any sensor failure

**Automation engine** 🔜 (Phase 2)
- Ventilation, irrigation, grow lights, misting with **hysteresis** and minimum on/off times
- Safety interlocks, modes (AUTO / MANUAL / OFF), timed manual override, **emergency stop**
- Every decision logged with the rule and the readings that caused it

**Dashboard & analytics** 🔜 (Phase 3)
- Live zone monitoring, charts, manual controls, scenario panel, alerts
- Water consumption, irrigation duration, energy use, threshold violations, zone comparison

**Intelligence** 🔜 (Phase 4)
- Anomaly detection evaluated against injected, labelled faults
- Predictive irrigation, water and energy optimisation, crop advisor

## 🏗️ How it works: architecture

```
 ┌────────────────────────────────────────────────────────────────────────────┐
 │                         SIMULATION ENGINE (Python)                         │
 │  Weather & sun ─► Physics per zone (energy, vapour, CO₂, soil water, light) │
 │                     ▲ actuator effects                │ true state          │
 └─────────────────────┼─────────────────────────────────┼─────────────────────┘
                       │                                 ▼
 ┌─────────────────────┴─────────────────────────────────────────────────────┐
 │                               DEVICE LAYER                                │
 │  SimActuator         ◄── commands      SimSensor (noise, lag, faults)      │
 │  MQTT actuator       (future ESP32)    MQTT sensor (future ESP32)          │
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

Design principles:

1. **True state vs. measured state.** Physics computes the *true* climate. Sensors then add the
   imperfections of real hardware (noise, lag, resolution, drift, saturation, faults). The automation
   engine only ever sees sensor readings, just like a real controller.
2. **Pure core.** `agrisense_core` (physics, devices, control) has no web dependencies. It is fully
   unit-testable and could run on a Raspberry Pi gateway.
3. **Simulated clock** with a speed multiplier. Physics integrates in fixed sub-steps (1 to 10 s)
   for numerical stability regardless of speed.
4. **SI units internally**, conversions only at the edges (UI, sensor raw values).
5. **Deterministic:** every random process draws from its own generator spawned from one seed.

## 🔬 The physics model

Each zone is modelled as a well-mixed "lumped" volume of air above a crop canopy and a soil root
zone, using established greenhouse-climate and FAO-56 crop-water equations
(`backend/agrisense_core/sim/`).

| Sub-model | What it computes | Main drivers |
|---|---|---|
| **Weather & sun** (`weather.py`) | Outside temperature, dew point, humidity, wind, cloud, rain, solar radiation | Latitude, longitude, day of year, equation of time, Haurwitz clear-sky model, Kasten cloud attenuation |
| **Radiation** | Light inside, canopy and soil shares | Cover transmissivity, Beer's law (k = 0.7) with leaf area index |
| **Air energy balance** | Inside air temperature | Absorbed sun, transpiration cooling, cover U-value, ventilation, soil exchange, lamps, heater, misting, condensation |
| **Vapour balance** | Humidity, VPD, condensation, fog | Transpiration, soil evaporation, misting, ventilation, condensation on the cooler cover (Tetens) |
| **Transpiration** | Crop water use | Stanghellini form of Penman-Monteith, light response of stomata, FAO-56 water-stress factor Ks |
| **CO₂ balance** | CO₂ ppm | Photosynthesis (light, CO₂ and temperature response), respiration (Q10 = 2), ventilation |
| **Soil water** | Volumetric water content | Drip irrigation, evapotranspiration, drainage above field capacity |
| **Soil temperature** | Root-zone temperature | Sun on bare soil, air exchange, deep soil |
| **Light** | PAR, DLI, lux | Sun through the cover plus LED grow lights |

Simplified air energy balance:

```
C · dT/dt = (Rn − λE + structure heat)·A − U·A_cover·(T_in − T_out) − ρ·cp·Q_vent·(T_in − T_out)
            + soil exchange + lamp heat + heater − misting cooling + condensation heat
```

where C is the heat capacity of the air plus canopy and structure.

Soil water balance (FAO-56 style):

```
dθ/dt = (irrigation − Ks·ET − drainage) / root_depth
```

Note: rain does **not** wet the soil inside a greenhouse. It cools and humidifies the outside air
and is harvested from the roof into the water tank.

## 📡 Simulated sensors

Each simulated sensor copies the behaviour of the real part listed in the
[hardware section](#-future-hardware-sensors-actuators--controllers)
(`backend/agrisense_core/devices/sensors.py`):

| Model | Measures | Raw output | Simulated imperfections |
|---|---|---|---|
| `sht31` | Air temp, RH | 16-bit words | ±0.3 °C / ±2 % RH per-unit bias, 8 s lag, saturation at 0/100 % |
| `capacitive_soil` | Soil VWC | 12-bit ADC counts (wetter = lower) | Two-point calibration, installation gain error, temperature drift, ADC noise, two probes per bed see slightly different soil |
| `ds18b20` | Soil temp | 1/16 °C steps | ±0.5 °C bias, 60 s lag |
| `bh1750` | Light | Counts (lux = counts / 1.2) | ±20 % gain, **saturates at about 54,600 lux** in strong sun |
| `scd30` | CO₂ | ppm | ±(30 ppm + 3 %), 2-minute warm-up |
| `jsn_sr04t` | Tank level | Echo distance (mm) | Speed-of-sound error with temperature, 25 cm blind zone, 1 % lost echoes |
| `yf_s201` | Irrigation flow | Pulse count (~450 per litre) | ±3 % K-factor, does not register below 1 L/min |

Every reading carries a quality flag: `ok`, `saturated`, `warming_up`, `fault` or `timeout`.

## ⚙️ Simulated actuators and hydraulics

| Actuator | ID pattern | Behaviour |
|---|---|---|
| Pump | `pump1` | Shared by all zones, max 15 L/min, 60 W |
| Zone valve | `A.valve` | Opens the zone's drip line |
| Fans | `A.fan` | PWM 0 to 1, 2 × 3,750 m³/h per zone (about 50 air changes per hour) |
| Grow light | `A.light` | LED, PPFD 150 to 200 µmol/m²/s, 3 to 4 kW per zone |
| Mister | `A.mister` | 20 L/h fog, raises humidity and cools by evaporation |
| Heater | `A.heater` | Optional, defined in `greenhouse.yaml` |

Water flows only when the pump runs, a zone valve is open and the tank has water. Flow per zone is
set by its drip emitters (for example 125 × 2 L/h) and shared proportionally if the pump is too small.
Commands can carry a time-to-live: when it expires the actuator switches off by itself, the same
fail-safe the ESP32 firmware will use if the server goes silent.

## 🎬 Scenarios

| Scenario | Default duration | Effect |
|---|---|---|
| `hot_day` | 12 h | Clear sky, +5 °C |
| `heatwave` | 72 h | Clear sky, +7 °C, more humid air |
| `rainfall` | 2 h | Rain at 10 mm/h: cooler, humid, tank refilled from the roof |
| `cloudy` | 24 h | Overcast sky |
| `cold_night` | 10 h | Clear sky, −6 °C |
| `humidity_spike` | instant | Zone RH jumps to 97 % |
| `dry_soil` | instant | Zone soil moisture falls to just above wilting point |
| `water_shortage` | instant | Tank drops to 5 % |
| `refill_tank` | instant | Tank refilled |
| `pump_failure` | 6 h | Pump runs and draws power but moves no water |
| `actuator_fault` | 6 h | Any actuator: failed, stuck on or stuck off |
| `sensor_failure` | 6 h | Any sensor: stuck, dropout, spike, drift or offset |

## ✅ Model validation

Automated tests (`backend/tests/test_physics_validation.py`) check the model against known
greenhouse behaviour. Results on a clear day in Colombo (latitude 6.9° N) with default settings:

| Check | Expected (literature) | AgriSense result |
|---|---|---|
| Closed greenhouse, midday, above outside temperature | 10 to 20 °C | about 13 °C |
| Fans at about 50 air changes/hour, midday | a few °C | about 1.7 °C |
| Tomato daily water use | 3 to 6 mm/day | 5.2 mm/day |
| Chilli daily water use | 3 to 6 mm/day | 4.8 mm/day |
| Lettuce daily water use (tropical, hot) | 2 to 5 mm/day | 4.2 mm/day |
| Daily light integral under the cover | 0.75 × outside (about 55 to 60) | about 42 mol/m²/day |
| CO₂ at night (respiration) | above outside | about 480 ppm |
| CO₂ in ventilated daylight (photosynthesis) | slightly below outside | about 413 ppm |
| Night humidity vs. midday | higher at night | yes |
| Water conservation | tank out = soil in + drainage + ET | exact (to 10⁻⁶) |
| Same seed | identical results | yes |

## 🧠 Automation & control logic (Phase 2)

Decisions will be evaluated in strict priority order:

| Priority | Layer | Example |
|---|---|---|
| 1 | **Emergency stop** | All actuators OFF and latched until manually reset |
| 2 | **Safety interlocks** | Tank < 10 %: pump locked out. Pump max run time. Failed sensor: fail-safe |
| 3 | **Manual override** | User forces fan ON for 30 min, then it automatically returns to AUTO |
| 4 | **Automatic rules** | Hysteresis bands: fan ON at 28 °C, OFF at 26 °C |
| 5 | **Schedules** | Grow lights allowed 06:00 to 20:00 when the DLI target is not reached |

Example rules (per-crop thresholds come from crop profiles):

| Condition | Action |
|---|---|
| Temperature above upper limit | Ventilation ON |
| Temperature back below (limit − hysteresis) | Ventilation OFF |
| Soil moisture below threshold | Open zone valve and start pump |
| Soil moisture reaches target | Stop irrigation |
| Tank critically low | Disable irrigation, raise CRITICAL alert |
| Light / DLI insufficient | Grow lights ON |
| Pump running but flow meter reads zero | Stop pump, raise pump-failure alert |
| Sensor stale or out of range | Mark sensor FAULT, loop goes to fail-safe, raise alert |

Every action will be logged with an explanation, for example
`Zone A · Fan ON · rule CLIMATE_HIGH_T · temp 29.4 °C > 28.0 °C`.

## 🌾 Greenhouse zones & crop profiles

Thresholds are crop-specific and growth-stage specific rather than one set for every plant.
Indicative day-time targets used as defaults (`crops.yaml`):

| Crop | Air temp | RH | Soil VWC | DLI |
|---|---|---|---|---|
| Tomato | 21 to 27 °C | 60 to 80 % | 25 to 30 % | 20 to 30 mol/m²/day |
| Chilli | 21 to 29 °C | 60 to 75 % | 22 to 28 % | 18 to 25 mol/m²/day |
| Lettuce | 15 to 21 °C | 60 to 75 % | 28 to 34 % | 12 to 17 mol/m²/day |

Each growth stage also defines leaf area index, root depth, stomatal resistance, the FAO-56
depletion fraction and maximum photosynthesis.

## 🗂️ Configuration files

All in `backend/agrisense_core/profiles/`, validated by Pydantic on load (`config.py`):

| File | Contents |
|---|---|
| `greenhouse.yaml` | Location, simulation start/step/seed, weather climate, cover, structure, tank, pump, zones with soil and equipment specs |
| `crops.yaml` | Crop growth stages and target ranges |
| `sensors.yaml` | Sensors installed per zone and greenhouse-wide, with `source: sim` or `source: mqtt` and calibration |

Default greenhouse: Colombo (6.9° N, 79.86° E, UTC+5:30), three zones of 10 m × 5 m × 3 m with a
single-layer polyethylene cover, a 2,000 L tank and roof rain-water harvesting.
To simulate your own greenhouse, copy the folder, edit it, and pass `--config <folder>`.

## 🧰 Technology stack

| Layer | Technology |
|---|---|
| Simulation & control | Python 3.12, NumPy, Pydantic, PyYAML (SciPy later for model calibration) |
| Backend API | FastAPI, Uvicorn, WebSockets, SQLAlchemy, Alembic |
| Database | SQLite (development), then PostgreSQL / TimescaleDB (deployment) |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS, Recharts |
| Machine learning | scikit-learn (anomaly detection, forecasting) |
| Quality | pytest, Ruff, ESLint, GitHub Actions |
| Deployment | Docker, Docker Compose |
| Future hardware link | MQTT (Mosquitto), ESP32 firmware |

## 📁 Project structure

```
agrisense-smart-greenhouse/
├── backend/
│   ├── agrisense_core/            # pure Python, no web framework
│   │   ├── sim/
│   │   │   ├── clock.py           # simulated time, speed multiplier, sub-steps
│   │   │   ├── psychro.py         # psychrometrics (FAO-56)
│   │   │   ├── weather.py         # sun position, radiation, outside weather
│   │   │   ├── physics.py         # zone energy, vapour, CO2, soil water model
│   │   │   ├── engine.py          # ties everything together, hydraulics, sampling
│   │   │   └── scenarios.py       # weather events, disturbances, faults
│   │   ├── devices/
│   │   │   ├── interfaces.py      # Reading, Command, driver protocols, MQTT topics
│   │   │   ├── bus.py             # in-process MQTT-style message bus
│   │   │   ├── sensors.py         # hardware-accurate simulated sensors
│   │   │   └── actuators.py       # simulated actuators with metering and faults
│   │   ├── control/               # rule engine (Phase 2)
│   │   ├── profiles/              # greenhouse.yaml, crops.yaml, sensors.yaml
│   │   ├── config.py              # Pydantic config schemas and loader
│   │   └── cli.py                 # command-line simulator
│   ├── app/                       # FastAPI application
│   │   ├── api/  ws/  db/  services/
│   │   ├── config.py
│   │   └── main.py
│   ├── tests/                     # 63 tests: physics validation, devices, engine, scenarios
│   └── pyproject.toml
├── frontend/                      # Next.js dashboard
├── ml/                            # Phase 4 experiments and models
├── infrastructure/                # Docker / compose / CI (Phase 5)
├── docs/IMPLEMENTATION_PLAN.md
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
pytest                                   # run all tests (about 30 s)
ruff check . && ruff format --check .    # lint
```

### Run the simulator from the command line

```bash
agrisense scenarios                                       # list scenarios
agrisense simulate --hours 24 --out day.csv               # one day, CSV every sim-minute
agrisense simulate --hours 48 --step 5 --fans-daytime --scenario hot_day --out hot.csv
agrisense simulate --hours 24 --seed 7 --config ./my-greenhouse
```

The CSV contains the outside weather, tank level and, per zone, the true temperature, humidity,
VPD, CO₂, soil moisture and temperature, PAR, DLI, transpiration, the SHT31 sensor reading and the
actuator states. One simulated day takes about 9 seconds at a 5 s step.

`--fans-daytime` runs the fans from 07:00 to 18:00. It is a stand-in until the Phase 2 controller.

### Use the engine from Python

```python
from agrisense_core.sim.engine import GreenhouseEngine

engine = GreenhouseEngine(seed=42, step_s=5)
engine.scenarios.start("hot_day")
engine.command("A.fan", 1.0, reason="demo")
engine.command("pump1", 1); engine.command("A.valve", 1, ttl_s=900)
engine.run_for(6 * 3600)
print(engine.snapshot()["zones"]["A"]["true"])
print(engine.latest[("A.air", "air_temp")])        # what the SHT31 reports
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
| **0: Foundation** ✅ | Repo structure, tooling, backend & frontend skeletons, docs | Health endpoint, tests and lint pass; dashboard shows API status |
| **1: Simulation engine** ✅ | Weather, physics per zone, actuator specs, sensor hardware models, device interfaces, scenarios, CLI | A simulated day is physically plausible, deterministic with a seed and validated by tests |
| **2: Automation engine** | Rules, hysteresis, interlocks, modes, override, emergency stop, fault detection | Every scenario (hot day, water shortage, sensor failure, ...) passes as an automated test |
| **3: API, storage & dashboard** | REST + WebSocket, database, live dashboard, scenario panel, analytics | Click "Simulate hot day" and watch the fan react live with an explained log entry |
| **4: Intelligence** | Anomaly detection, predictive irrigation, optimisation, crop advisor | Measured water/energy savings vs. rule-based control over a simulated week |
| **5: Deployment & polish** | Docker Compose, PostgreSQL/TimescaleDB, CI, docs, demo | `docker compose up` runs the whole platform |
| **6: Real hardware** | ESP32 firmware, MQTT drivers, calibration, shadow-mode digital twin | Real sensors feed the same dashboard; twin parameters fitted to real data |

Detailed plan: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

---

## 🔌 Future hardware: sensors, actuators & controllers

None of this is needed now. Every simulated sensor is modelled on a specific real part below, so
the software already expects that part's accuracy, range, raw output and failure modes.

### Controllers & communication

| Item | Recommended part | Qty | Purpose |
|---|---|---|---|
| Zone controller | **ESP32-WROOM-32 DevKit** or **ESP32-S3 DevKit** | 1 per zone (3) | Reads zone sensors, drives zone valve/fan/lights, Wi-Fi + MQTT |
| Gateway / server | **Raspberry Pi 4 or 5** (4 GB+), or a laptop | 1 | Runs Mosquitto MQTT broker, AgriSense backend, database, dashboard |
| MQTT broker | **Eclipse Mosquitto** (software) | 1 | Message bus between ESP32s and backend |
| Long-distance bus (optional) | **MAX485 RS-485 module** | as needed | For industrial sensors or cable runs longer than a few metres |

### Sensors (per zone unless stated)

| Measurement | Recommended sensor | Interface | Key specs (what the simulator models) | Qty |
|---|---|---|---|---|
| Air temperature & humidity | **Sensirion SHT31** (or SHT40) in a radiation shield. Budget: DHT22 | I²C | ±0.3 °C, ±2 % RH, 16-bit output, about 8 s response | 1 per zone + 1 outside |
| Soil moisture | **Capacitive soil moisture sensor v1.2** (corrosion-resistant). Pro: RS-485 soil sensor (moisture + temperature + EC) | Analog (ESP32 ADC) / RS-485 | Raw 0 to 4095 counts, needs dry/wet calibration, temperature drift | 2 per zone |
| Soil temperature | **DS18B20 waterproof probe** | 1-Wire | ±0.5 °C, 0.0625 °C resolution | 1 per zone |
| Light | **BH1750** lux sensor (saturates at about 54,600 lux in strong sun). Better: **TSL2591** (to about 88,000 lux). Pro: PAR quantum sensor | I²C / analog | Range, resolution, saturation; converted to PAR & DLI | 1 per zone |
| CO₂ | **Sensirion SCD30 / SCD40** (NDIR, also gives T/RH). Budget: MH-Z19B | I²C / UART | ±(30 ppm + 3 %), warm-up time, 2 s sampling | 1 per zone (or 1 shared) |
| Water tank level | **JSN-SR04T waterproof ultrasonic** plus a backup **float switch** for low level | GPIO / digital | Distance to level via tank geometry, 25 cm blind zone, occasional lost echoes | 1 per tank |
| Irrigation flow | **YF-S201 hall-effect flow meter** | Pulse (GPIO interrupt) | About 450 pulses/L; confirms the pump is really delivering water | 1 per irrigation line |
| Pump/fan feedback (optional) | **INA219** or **ACS712** current sensor | I²C / analog | Detects a running-but-failed or stalled device | per actuator |
| Outside weather (optional) | BME280 + rain sensor + anemometer | I²C / digital | Feeds the weather model with real data | 1 |

### Actuators

| Equipment | Recommended part | Driven by | Notes |
|---|---|---|---|
| Irrigation pump | **12 V DC diaphragm pump** (or submersible pump) | Relay / logic-level MOSFET | Flow (L/min) and power (W) are entered in `greenhouse.yaml` |
| Zone valves | **12 V normally-closed solenoid valve** | Relay / MOSFET + flyback diode | One per zone so zones irrigate independently; fails closed |
| Drip irrigation | Drip line / emitters (e.g. 2 L/h), filter, tubing | n/a | Emitter count × flow is used by the soil-water model |
| Ventilation fans | **12 V DC exhaust fans** (PWM capable) or AC fans | MOSFET (PWM) / SSR | Airflow (m³/h) defines the ventilation rate in the model |
| Grow lights | **Full-spectrum LED grow lights** | Relay / SSR | PPFD and wattage used for light and energy models |
| Vents / shade (optional) | Servo or 12 V linear actuator; shade screen motor | Motor driver (e.g. BTS7960) | Natural ventilation & shading |
| Misting / heating (optional) | Misting nozzles + pump; heater | Relay / SSR | Humidity raise / frost protection |
| Switching | **4- or 8-channel opto-isolated relay module**, or **IRLZ44N** logic-level MOSFETs, **SSR** for AC loads | ESP32 GPIO | Use flyback diodes on all inductive DC loads |

### Power & installation

| Item | Purpose |
|---|---|
| 12 V DC power supply (sized for pump + fans + valves + margin) | Main DC power |
| 12 V to 5 V buck converter (e.g. LM2596 / MP1584) | Powers ESP32 & sensors |
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

1. **Same message format.** AgriSense already uses MQTT-style topics on its internal bus
   (`devices/bus.py`, `devices/interfaces.py`):
   ```
   agrisense/{greenhouse}/{zone}/sensor/{sensor_id}/{quantity}  → {"value": 31.4, "unit": "%", "raw": 2310, "quality": "ok", "ts": "..."}
   agrisense/{greenhouse}/{zone}/actuator/{actuator_id}/set     ← {"level": 1, "reason": "SOIL_LOW", "ttl_s": 600}
   agrisense/{greenhouse}/{zone}/actuator/{actuator_id}/state   → {"level": 1, "commanded": 1, "confirmed": true}
   ```
   Greenhouse-wide devices use `gh` as the zone. ESP32 firmware will publish and subscribe to
   exactly these topics.
2. **Per-device source switch.** In `sensors.yaml` each device is `source: sim` or `source: mqtt`.
   A sensor marked `mqtt` is no longer simulated, so you can connect a single real sensor while
   the rest stays simulated (hardware-in-the-loop).
3. **Calibration** is stored per sensor (for example the capacitive soil sensor's raw count at 0 %
   and 50 % VWC), so real raw readings convert to the same units the simulator uses.
4. **Command confirmation.** Actuator commands are confirmed by feedback (flow meter, current
   sensor). A pump that runs but delivers no water can already be simulated with `pump_failure`.
5. **Shadow-mode digital twin.** With real sensors connected, the simulator runs in parallel using
   the same actuator states. Differences between predicted and measured values are used to fit the
   model parameters (cover U-value, transmissivity, ventilation rate) so the twin matches *your*
   greenhouse and can be used for prediction and optimisation.
6. **Fail-safe firmware.** ESP32s turn actuators off if they lose contact with the server
   (`ttl_s` in each command), and the float switch hard-wires a pump cut-off independent of software.

## ⚠️ Safety notes

- Work with **12 V DC** wherever possible. Any **mains (AC) wiring** (pumps, heaters, large fans,
  grow lights) must use certified SSRs/contactors, an RCD/GFCI and proper enclosures, and should be
  installed or checked by a qualified electrician.
- Keep electronics in sealed enclosures away from irrigation water.
- Software interlocks are not a substitute for hardware protection: use fuses, a float switch for
  dry-run protection and normally-closed valves that fail safe.

---

*AgriSense is a learning and portfolio project. Crop thresholds are indicative defaults; check
local agricultural guidance for your crop variety and climate.*
