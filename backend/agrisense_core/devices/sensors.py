"""Simulated sensors modelled on the specific hardware AgriSense will use.

Each model reproduces what the real part reports: its raw output (ADC counts, 16-bit words,
echo distance, pulse counts), calibration back to engineering units, accuracy (a fixed
per-device bias drawn once, like a real unit), noise, response lag, resolution, range limits
and typical failure modes. The controller only ever sees these readings, never the true state.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum

import numpy as np

from agrisense_core.devices.interfaces import Quality, Reading

Truth = Callable[[], dict[str, float]]


class SensorFault(StrEnum):
    STUCK = "stuck"  # value frozen at the last good reading
    DROPOUT = "dropout"  # no response
    SPIKE = "spike"  # intermittent large errors (loose connector, EMI)
    DRIFT = "drift"  # error grows by `magnitude` units per hour
    OFFSET = "offset"  # constant error of `magnitude` units


class _Lag:
    """First-order sensor response."""

    def __init__(self, tau_s: float) -> None:
        self.tau = tau_s
        self.y: float | None = None
        self.t: datetime | None = None

    def __call__(self, x: float, now: datetime) -> float:
        if self.y is None or self.t is None or self.tau <= 0:
            self.y = x
        else:
            dt = max(0.0, (now - self.t).total_seconds())
            self.y += (x - self.y) * (1 - math.exp(-dt / self.tau))
        self.t = now
        return self.y


class SimSensor:
    model = "base"
    warmup_s = 0.0

    def __init__(
        self,
        sensor_id: str,
        zone_id: str | None,
        sample_interval_s: float,
        truth: Truth,
        rng: np.random.Generator,
        calibration: dict[str, float] | None = None,
    ) -> None:
        self.sensor_id = sensor_id
        self.zone_id = zone_id
        self.sample_interval_s = sample_interval_s
        self.truth = truth
        self.rng = rng
        self.calibration = dict(calibration or {})
        self.fault: SensorFault | None = None
        self.fault_magnitude = 0.0
        self._fault_started: datetime | None = None
        self._last_read: datetime | None = None
        self._first_read: datetime | None = None
        self._last_values: dict[str, Reading] = {}
        self._init_device()

    def _init_device(self) -> None:
        """Draw per-device manufacturing errors."""

    # -- driver interface ------------------------------------------------------------------

    def due(self, now: datetime) -> bool:
        if self._last_read is None:
            return True
        return (now - self._last_read).total_seconds() >= self.sample_interval_s - 1e-9

    def read(self, now: datetime) -> list[Reading]:
        if self._first_read is None:
            self._first_read = now
        readings = self._measure(self.truth(), now)
        self._last_read = now
        return [self._apply_fault(r, now) for r in readings]

    def inject_fault(
        self, fault: SensorFault | None, magnitude: float = 0.0, now: datetime | None = None
    ) -> None:
        self.fault = fault
        self.fault_magnitude = magnitude
        self._fault_started = now

    # -- helpers ---------------------------------------------------------------------------

    def _make(
        self,
        quantity: str,
        value: float | None,
        unit: str,
        raw: float | None,
        quality: Quality,
        now: datetime,
    ) -> Reading:
        if quality is Quality.OK and self._warming(now):
            quality = Quality.WARMING_UP
        return Reading(self.sensor_id, self.zone_id, quantity, value, unit, raw, quality, now)

    def _warming(self, now: datetime) -> bool:
        return self._first_read is not None and (
            (now - self._first_read).total_seconds() < self.warmup_s
        )

    def _apply_fault(self, r: Reading, now: datetime) -> Reading:
        f = self.fault
        if f is None or r.value is None:
            if r.quality in (Quality.OK, Quality.WARMING_UP):
                self._last_values[r.quantity] = r
            return r
        if f is SensorFault.DROPOUT:
            return Reading(
                r.sensor_id, r.zone_id, r.quantity, None, r.unit, None, Quality.TIMEOUT, now
            )
        if f is SensorFault.STUCK:
            last = self._last_values.get(r.quantity, r)
            return Reading(
                r.sensor_id, r.zone_id, r.quantity, last.value, r.unit, last.raw, last.quality, now
            )
        err = 0.0
        if f is SensorFault.OFFSET:
            err = self.fault_magnitude
        elif f is SensorFault.DRIFT:
            start = self._fault_started or now
            err = self.fault_magnitude * (now - start).total_seconds() / 3600
        elif f is SensorFault.SPIKE and self.rng.random() < 0.2:
            err = self.fault_magnitude * (1 if self.rng.random() < 0.5 else -1)
        return Reading(
            r.sensor_id,
            r.zone_id,
            r.quantity,
            round(r.value + err, 4),
            r.unit,
            r.raw,
            r.quality,
            now,
        )


# --------------------------------------------------------------------------- SHT31


class SHT31(SimSensor):
    """Sensirion SHT31: I2C temperature/humidity, 16-bit outputs.
    Accuracy +/-0.3 degC, +/-2 %RH; response time ~8 s (in a radiation shield)."""

    model = "sht31"

    def _init_device(self) -> None:
        self.t_bias = self.rng.normal(0, 0.15)
        self.rh_bias = self.rng.normal(0, 1.0)
        self.t_lag = _Lag(8.0)
        self.rh_lag = _Lag(8.0)

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        t = self.t_lag(truth["air_temp"], now) + self.t_bias + self.rng.normal(0, 0.04)
        rh = self.rh_lag(truth["air_rh"], now) + self.rh_bias + self.rng.normal(0, 0.15)
        raw_t = int(round(max(0, min(65535, (t + 45) / 175 * 65535))))
        raw_rh = int(round(max(0, min(65535, rh / 100 * 65535))))
        t_val = -45 + 175 * raw_t / 65535
        rh_val = 100 * raw_rh / 65535
        rh_q = Quality.SATURATED if raw_rh in (0, 65535) else Quality.OK
        return [
            self._make("air_temp", round(t_val, 2), "degC", raw_t, Quality.OK, now),
            self._make("air_rh", round(rh_val, 2), "%", raw_rh, rh_q, now),
        ]


# --------------------------------------------------------------------------- capacitive soil


class CapacitiveSoil(SimSensor):
    """Capacitive soil moisture sensor v1.2 on a 12-bit ESP32 ADC.
    Output voltage falls as soil gets wetter. Two-point calibration maps raw counts to VWC;
    the raw value also drifts slightly with soil temperature, which calibration does not remove."""

    model = "capacitive_soil"
    TEMP_COEFF_COUNTS_PER_C = 3.0

    def _init_device(self) -> None:
        self.raw0 = self.calibration.get("raw_at_vwc0", 3300.0)
        self.raw50 = self.calibration.get("raw_at_vwc50", 1400.0)
        # Real installed response differs a little from the bench calibration.
        self.gain_err = self.rng.normal(0, 0.03)
        self.lag = _Lag(30.0)

    def _vwc_to_raw(self, vwc: float) -> float:
        return self.raw0 + (self.raw50 - self.raw0) * vwc / 0.5

    def _raw_to_vwc(self, raw: float) -> float:
        return 0.5 * (raw - self.raw0) / (self.raw50 - self.raw0)

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        vwc = self.lag(truth["soil_vwc"], now) * (1 + self.gain_err)
        raw = self._vwc_to_raw(vwc)
        raw += self.TEMP_COEFF_COUNTS_PER_C * (truth.get("soil_temp", 25.0) - 25.0)
        raw += self.rng.normal(0, 8.0)
        raw = int(round(max(0, min(4095, raw))))
        q = Quality.SATURATED if raw in (0, 4095) else Quality.OK
        value = max(0.0, self._raw_to_vwc(raw)) * 100
        return [self._make("soil_vwc", round(value, 2), "%", raw, q, now)]


# --------------------------------------------------------------------------- DS18B20


class DS18B20(SimSensor):
    """Maxim DS18B20 1-Wire waterproof probe: +/-0.5 degC, 12-bit (0.0625 degC) resolution."""

    model = "ds18b20"

    def _init_device(self) -> None:
        self.bias = self.rng.normal(0, 0.2)
        self.lag = _Lag(60.0)

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        t = self.lag(truth["soil_temp"], now) + self.bias + self.rng.normal(0, 0.03)
        raw = int(round(t / 0.0625))
        return [self._make("soil_temp", raw * 0.0625, "degC", raw, Quality.OK, now)]


# --------------------------------------------------------------------------- BH1750


class BH1750(SimSensor):
    """ROHM BH1750 ambient light sensor, high-resolution mode: lux = counts / 1.2.
    The 16-bit counter saturates at 65535 counts, i.e. ~54,600 lux, which full tropical sun
    exceeds even under a greenhouse cover. Accuracy +/-20 %."""

    model = "bh1750"

    def _init_device(self) -> None:
        self.gain = 1 + self.rng.normal(0, 0.07)

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        lux = truth["lux"] * self.gain * (1 + self.rng.normal(0, 0.01))
        raw = int(round(max(0.0, min(65535.0, lux * 1.2))))
        q = Quality.SATURATED if raw >= 65535 else Quality.OK
        return [self._make("light_lux", round(raw / 1.2, 1), "lux", raw, q, now)]


# --------------------------------------------------------------------------- SCD30


class SCD30(SimSensor):
    """Sensirion SCD30 NDIR CO2 sensor: +/-(30 ppm + 3 %), 0..10,000 ppm, needs warm-up."""

    model = "scd30"
    warmup_s = 120.0

    def _init_device(self) -> None:
        self.offset = self.rng.normal(0, 15)
        self.gain = 1 + self.rng.normal(0, 0.015)
        self.lag = _Lag(20.0)

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        c = self.lag(truth["co2_ppm"], now) * self.gain + self.offset + self.rng.normal(0, 5)
        c = max(0.0, min(10000.0, c))
        q = Quality.SATURATED if c >= 10000 else Quality.OK
        return [self._make("co2_ppm", float(round(c)), "ppm", round(c), q, now)]


# --------------------------------------------------------------------------- JSN-SR04T


class JSNSR04T(SimSensor):
    """Waterproof ultrasonic distance sensor mounted above the tank, looking down.
    Raw output is the echo distance in mm (firmware assumes 343 m/s, so air temperature
    causes a small error). Minimum range ~0.25 m: the sensor is mounted 0.30 m above the
    full level. Echoes are occasionally lost (TIMEOUT)."""

    model = "jsn_sr04t"
    MOUNT_GAP_M = 0.30
    BLIND_ZONE_M = 0.25
    MAX_RANGE_M = 4.5
    DROPOUT_P = 0.01

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        height = truth["tank_height_m"]
        water = truth["tank_level_frac"] * height
        distance = height + self.MOUNT_GAP_M - water
        speed_true = 331.3 + 0.606 * truth.get("air_temp", 20.0)
        measured = distance * 343.0 / speed_true + self.rng.normal(0, 0.004)
        if self.rng.random() < self.DROPOUT_P or not (
            self.BLIND_ZONE_M < measured < self.MAX_RANGE_M
        ):
            return [self._make("tank_level", None, "%", None, Quality.TIMEOUT, now)]
        raw_mm = int(round(measured * 1000))
        level = (height + self.MOUNT_GAP_M - raw_mm / 1000) / height * 100
        return [
            self._make(
                "tank_level", round(max(0.0, min(100.0, level)), 1), "%", raw_mm, Quality.OK, now
            )
        ]


# --------------------------------------------------------------------------- YF-S201


class YFS201(SimSensor):
    """YF-S201 hall-effect flow meter: ~450 pulses per litre (F = 7.5 * Q[L/min]), +/-3 %.
    Below ~1 L/min the rotor does not turn reliably. Reports flow averaged over the sample
    interval from the pulse count, exactly as the firmware's interrupt counter does."""

    model = "yf_s201"
    PULSES_PER_L = 450.0
    MIN_FLOW_LPM = 1.0

    def _init_device(self) -> None:
        self.k_err = 1 + self.rng.normal(0, 0.03)
        self._last_total: float | None = None
        self._carry = 0.0

    def _measure(self, truth: dict[str, float], now: datetime) -> list[Reading]:
        total = truth["flow_total_l"]
        interval = (now - self._last_read).total_seconds() if self._last_read else 0.0
        volume = 0.0 if self._last_total is None else max(0.0, total - self._last_total)
        self._last_total = total
        lpm_true = volume / interval * 60 if interval > 0 else 0.0
        if lpm_true < self.MIN_FLOW_LPM:
            volume = 0.0
        exact = volume * self.PULSES_PER_L * self.k_err + self._carry
        pulses = int(exact)
        self._carry = exact - pulses
        lpm = pulses / self.PULSES_PER_L / interval * 60 if interval > 0 else 0.0
        return [self._make("flow_lpm", round(lpm, 2), "L/min", pulses, Quality.OK, now)]


SENSOR_MODELS: dict[str, type[SimSensor]] = {
    cls.model: cls for cls in (SHT31, CapacitiveSoil, DS18B20, BH1750, SCD30, JSNSR04T, YFS201)
}
