# 🌱 AgriSense: Smart Greenhouse Simulation & Automation Platform

> A software-based smart greenhouse platform featuring physics-based virtual sensor simulation,
> automated irrigation, climate control, environmental analytics and AI-driven agricultural optimisation.
> Built **hardware-independent today, hardware-ready for tomorrow.**

**Status:** Phases 1 to 4 implemented: physics simulation, automation engine, API with storage
(SQLite or PostgreSQL/Neon) and a live web dashboard, and machine learning (anomaly detection,
irrigation forecasting, setpoint optimisation, crop advice). Next: Phase 5, deployment.
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
10. [Automation & control logic](#-automation--control-logic)
11. [API, storage & live dashboard](#-api-storage--live-dashboard)
12. [Intelligence (machine learning)](#-intelligence-machine-learning)
13. [Greenhouse zones & crop profiles](#-greenhouse-zones--crop-profiles)
14. [Configuration files](#-configuration-files)
15. [Technology stack](#-technology-stack)
16. [Project structure](#-project-structure)
17. [Getting started](#-getting-started)
18. [Roadmap](#-roadmap)
19. [Future hardware: sensors, actuators & controllers](#-future-hardware-sensors-actuators--controllers)
20. [Moving from simulation to real hardware](#-moving-from-simulation-to-real-hardware)
21. [Safety notes](#-safety-notes)

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

**Automation engine** ✅
- Controller sees only sensor readings from the message bus, never the true physics state
- Staged fan ventilation, humidity venting, fan-and-fog misting, drip irrigation cycles,
  DLI-based grow lights, heating, all with **hysteresis** and minimum on/off times
- Safety interlocks: tank dry-run lockout, pump no-flow alarm, pump run limit, high-temperature
  emergency, unexpected flow
- Sensor health monitoring (stale, out of range, spikes, stuck, probe disagreement) with
  fail-safe behaviour for every control loop
- Modes (AUTO / MANUAL / OFF), timed manual override, latched **emergency stop**
- Alerts (info / warning / critical, latched where dangerous) and an explained decision log

**API, storage & live dashboard** ✅
- FastAPI REST API and a WebSocket that streams the live greenhouse state twice per second
- The simulation runs inside the server at a selectable speed (1× to 3600×), with pause,
  fast-forward and new runs
- History stored in SQLite (PostgreSQL-ready through SQLAlchemy): climate per sim-minute,
  raw sensor readings, equipment meters, every decision and alert
- Next.js dashboard: overview, one page per zone (true vs. sensor charts against crop targets,
  equipment timeline, manual controls, sensor health), scenario panel, analytics, event log,
  emergency stop, light and dark themes
- Analytics: water supplied vs. crop use, energy by equipment, time outside crop targets,
  equipment activations and runtime, alerts by type

**Intelligence** ✅ (Phase 4)
- Sensor anomaly detection: four detectors compared on held-out simulations with labelled,
  injected faults, including a physics-informed "virtual sensor" that catches drift and offset
  faults the rules cannot see
- Predictive irrigation: hours until each zone needs water, compared with straight-line
  extrapolation
- Simulation-based optimisation of controller setpoints (energy vs. crop conditions), validated
  on unseen weather
- Crop advisor: explained recommendations from analytics, live state and model outputs
- Insights page in the dashboard, and forecasts on the overview

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

Closed-loop results (`backend/tests/test_control_scenarios.py`):

| Check | Without controller | With controller |
|---|---|---|
| Hot day (+5 °C), zone A peak temperature | 47.5 °C | 33.7 °C |
| Hot day, peak rise above outside | 12.1 °C | 0.7 °C (fans plus fog cooling) |
| Normal 72 h: irrigation | soil dries out | one cycle per zone when needed, VWC held in the crop band |
| Normal 72 h: zone A fan switching | n/a | 41 changes in 3 days (no chatter) |
| Normal 72 h: equipment energy | n/a | 30.2 kWh (20 % less than keeping fans on at night, same temperatures) |

## 🧠 Automation & control logic

The controller (`backend/agrisense_core/control/`) only sees sensor readings arriving on the
message bus and only acts by publishing actuator commands, exactly as it will with real ESP32
hardware. Commands carry a 60 s time-to-live, so if the controller crashes every actuator
switches itself off. Behaviour is configured in `profiles/control.yaml`; crop targets come from
`profiles/crops.yaml`. The control loop runs every 10 simulated seconds.

### Priority layers

Every actuator is decided through strict layers on every tick:

| Priority | Layer | Example |
|---|---|---|
| 1 | **Emergency stop** | All actuators OFF, latched until an operator resets it |
| 2 | **Safety interlocks** | FORCE (fans to 100 % at 40 °C) or BLOCK (no pumping from a dry tank) |
| 3 | **Operator mode** | MANUAL level, timed override (returns to AUTO by itself) or OFF |
| 4 | **Automatic rules** | Crop-specific targets with hysteresis |
| 5 | **Minimum on/off times** | Protect motors and relays (automatic decisions only) |

Interlock blocks also apply to manual commands: an operator cannot run the pump dry.

### Automatic rules

| Equipment | Rule |
|---|---|
| **Fans (temperature)** | Stage 1 (50 %) above the crop's day or night maximum, stage 2 (100 %) at max + 2 °C, OFF at max − 1.5 °C. Only switch on if inside is at least 1 °C warmer than outside (ventilation would not cool otherwise). By day keep running until outside becomes 0.5 °C warmer than inside (a small difference is what working fans achieve against the sun); at night stop once inside is within 0.3 °C of outside, since there is no solar load and venting would only waste energy |
| **Fans (humidity)** | Vent at RH > max + 5 %, until RH < max − 2.5 %, only if the outside air holds less water (absolute humidity check with its own hysteresis). Temperature has priority: never vent for humidity if it would heat a zone already above its maximum |
| **Mister** | Fog cooling when temperature > max + 2 °C and RH < max − 5 % (pulse misting, fans kept running: fan-and-fog). Humidifies when RH < min − 5 % |
| **Irrigation** | Valve opens when soil VWC (average of healthy probes) falls below the crop minimum, closes at min + 60 % of the band. A cycle longer than 3 h stops, soaks 15 min and raises `IRRIGATION_TIMEOUT` (leak, clogged emitters or misplaced probe). The pump runs whenever any valve is open |
| **Grow lights** | Allowed 06:00 to 20:00. ON when the measured daily light integral falls behind a sun-shaped pace towards the crop minimum and the sun is weak; OFF when back on pace, the sun is bright or the minimum is reached. The controller subtracts the lamps' own light from the lux reading to estimate sunlight |
| **Heater** | ON below the crop minimum, OFF at minimum + 1.5 °C (if a heater is configured) |

### Safety interlocks

| Interlock | Trigger | Action | Alert |
|---|---|---|---|
| Tank dry-run protection | Tank < 10 % (released above 15 %) | Pump, valves and misters blocked | `TANK_CRITICAL` (critical), `TANK_LOW` below 20 % |
| Tank level unknown | No valid tank reading | Pump, valves and misters blocked | `TANK_LEVEL_UNKNOWN` (critical) |
| Pump no-flow | Pump on > 30 s but flow meter < 0.5 L/min | Pump blocked until an operator resets the alarm | `PUMP_NO_FLOW` (critical, **latched**) |
| Pump run limit | Pump on continuously for 4 h | 10 min rest | `PUMP_MAX_RUNTIME` |
| Unexpected flow | Flow with the pump off | Alert only (stuck relay or leak) | `UNEXPECTED_FLOW` |
| High temperature | Zone ≥ 40 °C (cleared at 37 °C) | Fans forced to 100 %, even in mode OFF | `HIGH_TEMP_EMERGENCY` (critical) |

### Sensor health and fail-safes

Every reading passes the health monitor (`control/health.py`) before the rules may use it:

| Problem | Detection |
|---|---|
| Stale | No accepted reading for 30 s (or 3 sample intervals) |
| Out of range | Outside physically plausible limits (`control.yaml`) |
| Spikes | 3 jumps faster than physics allows within 5 min; spikes are never used. A genuine step change (three consistent new readings) is accepted |
| Stuck | Value unchanged for 10 min on a quantity that always fluctuates |
| Probe disagreement | The two soil probes of a bed differ by more than 6 % VWC |
| Saturated | Still usable as a bound (e.g. BH1750 in full sun) |

If a control loop loses its sensor it falls back to a safe behaviour and raises an alert:

| Loop | Fail-safe |
|---|---|
| Climate (no air temperature) | Fans at 50 % by day, off at night; misting and heating off |
| Irrigation (no soil moisture) | Timed irrigation: 10 min every 6 h |
| Lighting (no light reading) | Grow lights off |
| Tank (no level reading) | Pump locked out |

Limitation: a slow drift or constant offset on a single sensor cannot be detected by rules alone.
It is caught when redundant probes disagree, and by the Phase 4 virtual-sensor anomaly detector
(see [Intelligence](#-intelligence-machine-learning)).

### Alerts and decision log

Alerts have a severity (`info`, `warning`, `critical`), are deduplicated, clear automatically when
the cause is gone, and dangerous ones are **latched** (`PUMP_NO_FLOW`, `EMERGENCY_STOP`) until an
operator resets them. Sustained out-of-range conditions (30 min) raise `TEMP_OUT_OF_RANGE` and
`RH_OUT_OF_RANGE`.

Every actuator change is recorded with its rule and readings, and published on
`agrisense/{greenhouse}/control/decision`:

```
2026-03-22 11:00:25  Zone C · Valve ON · SOIL_LOW · VWC 27.9 % (start 28 %, stop 31.6 %)
2026-03-22 11:00:25  Greenhouse · Pump ON · IRRIGATION_DEMAND · open valves: C.valve
2026-03-21 08:49:25  Zone A · Fans ON · CLIMATE_VERY_HIGH_T · temp 29.0 degC > 29 degC, +1.3 degC vs outside
2026-03-21 16:08:45  Zone A · Grow lights ON · DLI_DEFICIT · DLI 14.5/20 mol (pace 16.5), sun 299 umol
```

### Operator controls

```python
ctl = runtime.controller
ctl.override("A.fan", 1.0, duration_s=1800, now=runtime.now)   # 30 min, then back to AUTO
ctl.set_mode("C.mister", "off")                                 # AUTO | MANUAL | OFF
ctl.emergency_stop(runtime.now, reason="maintenance")           # everything off, latched
ctl.reset_emergency(runtime.now)
ctl.reset_alarm("PUMP_NO_FLOW", runtime.now, scope="pump1")     # after repairing the pump
```

Note for the tropical default location: lettuce is a cool-season crop, so in lowland Colombo
it stays above its temperature target at night and `TEMP_OUT_OF_RANGE` warnings are expected.
That is the system correctly reporting a climate the equipment cannot fix.

## 🖥️ API, storage & live dashboard

### How the server runs the greenhouse

When the API server starts, it creates the simulator and the controller and advances them in a
background loop at the configured speed (default 60×: one simulated minute per real second).
Everything (the loop and every request handler) runs on the server's event-loop thread, so the
simulation state never needs locks. The loop caps the physics steps per slice; if the machine
cannot keep up at a very high speed, the dashboard shows "lagging" instead of the API freezing.

### Storage

Each simulation run gets its own history (a new run starts with **New simulation run** or
`POST /api/sim/reset`; the last 5 runs are kept, and each run keeps its last 30 simulated days).

| Table | Content | Stored every |
|---|---|---|
| `zone_states` | True climate and soil state, what the controller measured, equipment levels, water totals | 1 simulated minute |
| `greenhouse_states` | Outside weather, tank level, rain harvested, active alert count | 1 simulated minute |
| `actuator_states` | Level, cumulative energy, runtime and starts per actuator | 1 simulated minute |
| `sensor_readings` | Raw readings exactly as the controller received them (value, raw, quality) | 5 simulated minutes |
| `decisions` | Every controller decision with its rule and explanation | every change |
| `alerts` | Every alert with raise and clear times | every change |

Two databases are supported through SQLAlchemy, chosen by `AGRISENSE_DATABASE_URL`:

| Database | When | Notes |
|---|---|---|
| **SQLite** (default) | Development, tests | Zero setup, file `backend/agrisense.db` |
| **PostgreSQL** | Persistent or cloud storage, e.g. a free **Neon** serverless database | Paste the Neon URL (`postgresql://...`); the psycopg 3 driver is used automatically |

Tables are created automatically on startup (schema migrations with Alembic arrive in Phase 5).

How storage stays fast on a remote database (each round trip to Neon took about 350 ms in testing):

- **Background writes:** history is written every 2 s in one batched transaction on a worker
  thread, so the simulation, the API and the WebSocket never wait for the database. A write
  that fails (network blip) is retried, not lost. The overview's System card shows the last write
  and any errors.
- **Read-only autocommit queries** in worker threads: one round trip per query instead of four.
- **Analytics aggregated in SQL** (`GROUP BY`, first/last meter rows) instead of downloading every
  row: the 24 h summary went from 27 s to about 2 to 4 s on Neon; history and decisions take
  about 0.5 s.
- On a remote database, reads do not wait for the latest write, so charts can lag the live view
  by a few seconds (2 to 3 simulated minutes at 60×).
- Storage use is about **5 MB per simulated day**. At 60× that is roughly 300 MB per real day of
  continuous running, so `AGRISENSE_RETAIN_DAYS` (default 30 simulated days) prunes older history.
  Check your database plan's storage limit.

**Troubleshooting Neon connections:** if the connection times out although the host is reachable,
something on the network (firewall, antivirus or ISP) is probably dropping PostgreSQL's
plaintext SSL start message. Append `&sslnegotiation=direct` to the URL: the client then starts
TLS immediately (needs libpq 17+, bundled with the installed driver). This was required on the
development machine.

### REST API

Interactive documentation: `http://localhost:8000/docs`.

| Method & path | Purpose |
|---|---|
| `GET /api/health` | Server status |
| `GET /api/config` | Zones, crop targets, equipment, scenario catalogue |
| `GET /api/state` | Live state (same as the WebSocket message) |
| `GET /api/sensors` | Latest reading, raw value, quality and health of every sensor |
| `POST /api/sim/speed` `{speed}` | Simulation speed (simulated seconds per real second) |
| `POST /api/sim/pause`, `/api/sim/resume` | Pause and resume |
| `POST /api/sim/advance` `{hours}` | Fast-forward (about 3 s per simulated day) |
| `POST /api/sim/reset` `{seed?}` | Start a new run |
| `GET/POST /api/scenarios`, `DELETE /api/scenarios/{id}` | List, start and stop scenarios |
| `POST /api/actuators/{id}/override` `{level, duration_min}` | Timed manual override |
| `POST /api/actuators/{id}/mode` `{mode, level}` | AUTO / MANUAL / OFF |
| `POST /api/emergency-stop`, `/api/emergency-stop/reset` | Emergency stop and reset |
| `POST /api/alerts/reset` `{code, scope}` | Reset a latched alarm such as `PUMP_NO_FLOW` |
| `GET /api/history/zones/{id}?hours=24` | Zone time series (auto-averaged to at most 720 points) |
| `GET /api/history/greenhouse?hours=24` | Weather and tank time series |
| `GET /api/decisions?zone=&actuator=&limit=` | Decision log |
| `GET /api/alerts?active_only=&severity=` | Alert history |
| `GET /api/analytics/summary?hours=24` | Water, energy, equipment use, time outside targets per zone |
| `GET /api/runs` | Simulation runs |
| `GET /api/intelligence/status`, `POST /api/intelligence/reload` | Model status, reload newly trained models |
| `GET /api/intelligence/anomalies` | Live anomaly score of every monitored sensor |
| `GET /api/intelligence/forecast` | Hours until each zone's next irrigation |
| `GET /api/intelligence/advice?hours=24` | Crop advisor recommendations with evidence |
| `GET /api/intelligence/report` | Offline evaluation results |
| `WS /ws/live` | Live state pushed twice per second |

### Dashboard pages

| Page | What it shows |
|---|---|
| **Overview** | Simulated clock and speed controls, outside weather, tank, one card per zone (measured values against crop targets with status icons, equipment states with the rule behind them, irrigation state), active alerts, latest decisions |
| **Zone A / B / C** | Charts of the true value and the sensor reading on top of the crop's day/night target band (temperature, humidity, soil moisture), light, an equipment timeline, manual controls for every actuator, sensor health with raw values, the zone's decisions |
| **Scenarios** | Every scenario with its parameters (zone, sensor, actuator, fault type, magnitude, duration); active scenarios with stop buttons; new run |
| **Analytics** | Time range filter, totals (water, rain harvested, energy, alerts), water per zone, energy by equipment, time outside crop targets, zone climate summary, equipment use, alerts by type |
| **Insights** | Crop advice, next-irrigation forecast per zone, live sensor anomaly table, and the held-out evaluation of every model |
| **Events** | Full decision log (filter by zone and equipment) and alert history (with reset for latched alarms) |

The charts use a colour-blind-validated palette in both light and dark mode. Status (OK, warning,
critical) is always shown with an icon and a label, never colour alone, and every chart has a
table view.

## 🤖 Intelligence (machine learning)

Code: `backend/agrisense_core/intelligence/`. Full results: [`ml/reports/phase4_results.md`](ml/reports/phase4_results.md).

**Method.** All data comes from the closed-loop simulator. A recorder captures, every simulated
minute, only what a real controller could know (sensor readings as received, its own equipment
levels and estimates), plus ground truth and fault labels kept apart for scoring. Training,
calibration and test data come from **different simulation seeds** (different weather, sensor
manufacturing errors and fault schedules): 28 runs, 108 simulated greenhouse-days, generated in
parallel. Every number below is measured on seeds the models never saw. The same feature code
is used offline and live, so the API scores exactly what was evaluated.

### 1. Sensor anomaly detection

Fault runs inject random sensor faults (stuck, spike, drift, offset, dropout) with realistic sizes
on the air, soil and CO₂ sensors of all zones. Four detectors are compared:

| Detector | How it works |
|---|---|
| Rules (Phase 2) | The controller's health monitor: stale, out of range, spikes, stuck, soil probe disagreement |
| IsolationForest | Unsupervised outlier detection on window and residual features |
| **Virtual sensor** | Analytical redundancy: a gradient-boosting model learns, on healthy data only, to predict each sensor from the other zones' sensors, the outside sensor, light and equipment state. A residual that stays away from the sensor's own 24 h baseline means the *sensor* changed, not the greenhouse. Needs no fault examples |
| Supervised | Gradient-boosting classifier trained on labelled simulated faults |

ML alarms are debounced (flagged in 5 of the last 10 minutes) and use **fault isolation**: one
faulty sensor also skews its peers' predictions, so within a group of the same quantity only
the most deviant sensor (or several with similar scores) is blamed.

Results on 197 healthy sensor-days plus 90 injected faults:

| Detector | Precision | Recall | Faults caught | False alarms per sensor-day |
|---|---|---|---|---|
| Rules | 86 % | 53 % | 74 % | 1.18 |
| IsolationForest | 62 % | 48 % | 78 % | 1.13 |
| Virtual sensor | 57 % | 66 % | 93 % | 0.33 |
| Supervised | 90 % | 84 % | 100 % | 0.17 |

| Fault type | Rules | Virtual sensor | Supervised |
|---|---|---|---|
| Stuck | 26/26 (10 min) | 26/26 (24 min) | 26/26 (7 min) |
| Spike | 20/20 (2 min) | 15/20 (58 min) | 20/20 (7 min) |
| **Drift** | **5/15** (137 min) | **14/15** (41 min) | 15/15 (54 min) |
| **Offset** | **10/22** (0 min) | **22/22** (4 min) | 22/22 (4 min) |

Faults caught, with median detection delay. What this shows:

- **The rules cannot see drift or offset** on a single sensor; they only catch those on soil
  probes, through probe disagreement. The virtual sensor catches nearly all of them, without
  ever seeing a fault example.
- **Rules and virtual sensor complement each other:** rules for spikes, stuck values and
  dropouts, the virtual sensor for drift and offset. The live dashboard flags a sensor when
  either ML detector does, next to the rules' verdict.
- **The supervised classifier scores best, but treat it as an upper bound:** it was trained on
  the same simulated fault types it is tested on. Real faults will differ; the virtual sensor's
  approach transfers better because it only learns what healthy looks like.
- **Debouncing and fault isolation matter:** they cut the virtual sensor's false alarms from 3.9
  to 0.33 per sensor-day, at the cost of a few minutes' delay and missing some intermittent
  spikes (which the rules catch).

### 2. Predictive irrigation

Hours until each zone's next irrigation starts, compared with straight-line extrapolation of
the last 3 h soil moisture trend (53,000 test minutes):

| Horizon | Model error | Straight-line error |
|---|---|---|
| All | **3.3 h** | 19.1 h |
| 0 to 6 h ahead | 2.8 h | 10.7 h |
| 6 to 24 h ahead | 2.7 h | 27.8 h |
| 24 to 48 h ahead | 3.9 h | 13.8 h |

As a yes/no question, "irrigation within 6 hours?", the model is right 92 % of the times it says
yes and finds 69 % of such cases (straight line: 76 % and 54 %). Soil dries fast at midday and
hardly at night, which a straight line cannot know; the model also receives the straight-line
estimate as a feature and learns corrections to it.

### 3. Controller setpoint optimisation

The simulator is used as a test bench: 31 sets of climate-control parameters (fan stages and
bands, ventilation thresholds, fog cooling offset, humidity band) were each run in closed loop
on 2 seeds × 2 days, in parallel. The rule: **lowest energy without more time outside crop
targets than the defaults**. The winner was then validated on 3 unseen seeds × 3 days:

| Metric | Default | Tuned | Change |
|---|---|---|---|
| Equipment energy | 26.1 kWh | 21.5 kWh | **−17.6 %** |
| Hours outside temperature targets | 199.2 | 199.0 | −0.1 % |
| Hours outside humidity targets | 145.8 | 150.3 | +3.1 % |
| Water | 874 L | 876 L | +0.2 % |

The saving mainly comes from starting fans only when inside is 2.4 °C (instead of 1 °C) warmer
than outside, and a wider hysteresis band. Humidity time-outside-target rose slightly on unseen
weather, which is the honest trade-off. The settings are in
[`ml/reports/optimized_control.yaml`](ml/reports/optimized_control.yaml) and are **not applied
automatically**: merge them into `control.yaml` if you accept the trade-off.

### 4. Crop advisor

Rule-based and explainable: every recommendation carries the evidence behind it. It covers
cooling capacity (shade screen, pad-and-fan, or crop/season mismatch such as lettuce in the
lowland tropics), disease risk from humidity, soil too dry or wet, CO₂ depletion, excess light,
water balance, irrigation timeouts, low tank, pump failure, sensor problems (including virtual-sensor
anomalies) and energy (pointing to the tuned setpoints).

### Train and run

```bash
cd backend
agrisense ml all            # datasets + training + evaluation + optimisation + report (~9 min on 8 cores)
agrisense ml train          # only datasets, models and evaluation
agrisense ml optimize       # only setpoint optimisation
agrisense ml all --quick    # small smoke run (~1 min)
```

Datasets (`ml/data/`) and models (`ml/models/`) are generated and git-ignored; reports
(`ml/reports/`) are committed. The API loads the models at startup (or `POST
/api/intelligence/reload`); without them, the Insights page shows how to train them and the
advisor still works.

**Limits.** Everything is learned from the simulator. With real sensors (Phase 6) the virtual
sensors and forecaster must be retrained on real healthy data. The pipeline is the same, only
the recorder's source changes.

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
| `control.yaml` | Controller behaviour: loop interval, command TTL, hysteresis bands, irrigation cycle limits, lighting window, tank and pump limits, sensor health limits, minimum on/off times. Optional: defaults apply if missing |

Default greenhouse: Colombo (6.9° N, 79.86° E, UTC+5:30), three zones of 10 m × 5 m × 3 m with a
single-layer polyethylene cover, a 2,000 L tank and roof rain-water harvesting.
To simulate your own greenhouse, copy the folder, edit it, and pass `--config <folder>`.

## 🧰 Technology stack

| Layer | Technology |
|---|---|
| Simulation & control | Python 3.12, NumPy, Pydantic, PyYAML (SciPy later for model calibration) |
| Backend API | FastAPI, Uvicorn, WebSockets, SQLAlchemy 2 (Alembic with PostgreSQL in Phase 5) |
| Database | SQLite (development) or PostgreSQL via psycopg 3 (tested on Neon serverless) |
| Frontend | Next.js 15.5 (patched release), React 19.1, TypeScript, Tailwind CSS 4, Recharts 3 |
| Machine learning | scikit-learn (HistGradientBoosting, IsolationForest), NumPy, joblib |
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
│   │   ├── intelligence/          # Phase 4: recorder, features, dataset, anomaly, forecast,
│   │   │                          #          optimize, advisor, pipeline, live scoring
│   │   ├── control/
│   │   │   ├── controller.py      # rules, interlocks, arbitration, decision log
│   │   │   ├── health.py          # sensor health monitor
│   │   │   ├── alerts.py          # alert manager (deduplicated, latched)
│   │   │   ├── hysteresis.py      # hysteresis switch, minimum on/off times
│   │   │   └── modes.py           # AUTO / MANUAL / OFF, timed overrides
│   │   ├── profiles/              # greenhouse.yaml, crops.yaml, sensors.yaml, control.yaml
│   │   ├── config.py              # Pydantic config schemas and loader
│   │   ├── runtime.py             # simulator + controller closed loop
│   │   ├── units.py               # light unit conversions
│   │   └── cli.py                 # command-line simulator
│   ├── app/                       # FastAPI application
│   │   ├── api/                   # sim.py, control.py, data.py, health.py routes
│   │   ├── ws/live.py             # live WebSocket
│   │   ├── db/                    # SQLAlchemy models and session
│   │   ├── services/
│   │   │   ├── simulation.py      # runs the greenhouse in the server, stores history
│   │   │   └── analytics.py       # history and analytics queries
│   │   ├── config.py              # settings (AGRISENSE_* environment variables)
│   │   └── main.py
│   ├── tests/                     # tests: physics, devices, engine, control, API, ML
│   └── pyproject.toml
├── frontend/                      # Next.js dashboard
│   ├── app/                       # pages: overview, zones/[id], scenarios, analytics, events
│   ├── components/                # shell, charts, actuators, events, ui
│   └── lib/                       # API client, live WebSocket provider, formatting
├── ml/
│   ├── reports/                   # Phase 4 results (committed): phase4_results.md/.json, optimized_control.yaml
│   ├── models/                    # trained models (generated, git-ignored)
│   └── data/                      # simulated datasets (generated, git-ignored)
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
uvicorn app.main:app                     # API + running simulation: http://localhost:8000/docs
pytest                                   # run all tests (about 2 min)
ruff check . && ruff format --check .    # lint
```

Server settings (in `backend/.env`, see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `AGRISENSE_DATABASE_URL` | `sqlite:///./agrisense.db` | Database: SQLite file or a `postgresql://` URL (e.g. Neon) |
| `AGRISENSE_SIM_SPEED` | `60` | Simulated seconds per real second |
| `AGRISENSE_SIM_STEP_S` | `5` | Physics step |
| `AGRISENSE_SEED` | random | Fixed seed for a reproducible run |
| `AGRISENSE_AUTOSTART` | `true` | Run the simulation when the server starts |
| `AGRISENSE_STATE_EVERY_S`, `AGRISENSE_READINGS_EVERY_S` | `60`, `300` | Storage intervals (simulated seconds) |
| `AGRISENSE_KEEP_RUNS` | `5` | Older runs are deleted |
| `AGRISENSE_RETAIN_DAYS` | `30` | Simulated days of history kept per run |
| `AGRISENSE_FLUSH_EVERY_S` | `2` | Real seconds between background history writes |
| `AGRISENSE_ML_DIR` | repository `ml/` | Trained models and reports |

The database password belongs only in `backend/.env`, which git ignores. Never commit it.

Avoid `--reload` while the simulation runs: every code change restarts the server and with it
the simulation run.

### Run the simulator from the command line

```bash
agrisense scenarios                                       # list scenarios
agrisense simulate --hours 24 --out day.csv               # closed loop, CSV every sim-minute
agrisense simulate --hours 48 --scenario hot_day --log decisions.txt
agrisense simulate --hours 24 --scenario water_shortage --scenario dry_soil --log log.txt
agrisense simulate --hours 24 --no-control --fans-daytime # open loop: fans on a fixed timer
agrisense simulate --hours 24 --seed 7 --config ./my-greenhouse
```

The controller is on by default. The CSV contains the outside weather, tank level and, per zone,
the true temperature, humidity, VPD, CO₂, soil moisture and temperature, PAR, DLI, transpiration,
the SHT31 sensor reading, the actuator states and the number of active alerts. `--log` writes
every explained decision and alert. The summary prints temperature and VWC ranges, water use,
equipment energy, decision counts and alerts. One simulated day takes about 12 seconds at a
10 s step.

### Use it from Python

```python
from agrisense_core.runtime import GreenhouseRuntime

rt = GreenhouseRuntime(seed=42, step_s=10)           # simulator + controller
rt.engine.scenarios.start("hot_day")
rt.run_for(14 * 3600)
for d in list(rt.controller.decisions)[-5:]:
    print(d.message)                                  # explained decisions
print(rt.controller.alerts.codes())                   # active alerts
print(rt.engine.latest[("A.air", "air_temp")])       # what the SHT31 reports
print(rt.snapshot()["zones"]["A"]["true"])           # what is really happening
```

`GreenhouseEngine` (in `agrisense_core.sim.engine`) can also be used on its own, without the
controller, sending commands with `engine.command("A.fan", 1.0)`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local               # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                              # http://localhost:3000
# or a production build:  npm run build && npm run start
npm run lint
```

Start the backend first, then open `http://localhost:3000`. A quick demo: press **+6 h** to
fast-forward to the morning, open **Scenarios**, start **Hot day** and **Dry soil** (zone B), then
watch the fans, misters and irrigation react on the zone pages and in the **Events** log.

## 🗺️ Roadmap

| Phase | Goal | Done when |
|---|---|---|
| **0: Foundation** ✅ | Repo structure, tooling, backend & frontend skeletons, docs | Health endpoint, tests and lint pass; dashboard shows API status |
| **1: Simulation engine** ✅ | Weather, physics per zone, actuator specs, sensor hardware models, device interfaces, scenarios, CLI | A simulated day is physically plausible, deterministic with a seed and validated by tests |
| **2: Automation engine** ✅ | Rules, hysteresis, interlocks, modes, override, emergency stop, sensor health, fail-safes, alerts, decision log | Every scenario (hot day, water shortage, pump failure, sensor failure, ...) passes as an automated test |
| **3: API, storage & dashboard** ✅ | REST + WebSocket, database, live dashboard, scenario panel, analytics | Click "Simulate hot day" and watch the fan react live with an explained log entry |
| **4: Intelligence** ✅ | Anomaly detection, predictive irrigation, optimisation, crop advisor | Measured water/energy savings vs. rule-based control over a simulated week |
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
