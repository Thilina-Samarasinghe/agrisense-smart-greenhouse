"""Outside weather: sun position, solar radiation, temperature, humidity, wind, cloud and rain.

The model is stochastic but fully reproducible from the seed. Scenarios can override parts of
it (for example a heatwave raises temperatures, a storm forces rain) through `overrides`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from agrisense_core.config import LocationConfig, WeatherConfig
from agrisense_core.sim import psychro

SOLAR_CONSTANT = 1367.0  # W/m2


@dataclass
class WeatherOverrides:
    """Adjustments applied on top of the stochastic weather (set by scenarios)."""

    temp_offset_c: float = 0.0
    dewpoint_offset_c: float = 0.0
    cloud: float | None = None
    rain_mm_h: float | None = None
    wind_ms: float | None = None


@dataclass
class WeatherState:
    temp_c: float
    dewpoint_c: float
    rh_pct: float
    chi: float  # absolute humidity, kg/m3
    solar_w_m2: float  # global horizontal irradiance
    clear_sky_w_m2: float
    sun_elevation_deg: float
    cloud: float
    wind_ms: float
    rain_mm_h: float
    co2_ppm: float


@dataclass
class _Stochastic:
    cloud: float
    wind_ms: float
    rain_remaining_s: float = 0.0
    rain_cooling_c: float = 0.0


def solar_declination_rad(day_of_year: int) -> float:
    return math.radians(23.45) * math.sin(2 * math.pi * (284 + day_of_year) / 365)


def equation_of_time_min(day_of_year: int) -> float:
    b = 2 * math.pi * (day_of_year - 81) / 364
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def solar_time_h(clock_hour: float, day_of_year: int, loc: LocationConfig) -> float:
    correction_min = 4 * (loc.longitude_deg - 15 * loc.utc_offset_hours)
    correction_min += equation_of_time_min(day_of_year)
    return (clock_hour + correction_min / 60) % 24


def sun_cos_zenith(solar_hour: float, day_of_year: int, latitude_deg: float) -> float:
    lat = math.radians(latitude_deg)
    dec = solar_declination_rad(day_of_year)
    omega = math.radians(15 * (solar_hour - 12))
    return math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(omega)


def clear_sky_ghi(cos_zenith: float) -> float:
    """Haurwitz clear-sky model, W/m2."""
    if cos_zenith <= 0.01:
        return 0.0
    return 1098.0 * cos_zenith * math.exp(-0.057 / cos_zenith)


def cloud_transmission(cloud: float) -> float:
    """Kasten-Czeplak attenuation by cloud cover fraction."""
    return 1.0 - 0.75 * cloud**3.4


class WeatherModel:
    CLOUD_TAU_S = 3 * 3600.0
    WIND_TAU_S = 1800.0
    RAIN_COOLING_C = 3.0
    RAIN_COOLING_TAU_S = 1800.0

    def __init__(self, cfg: WeatherConfig, loc: LocationConfig, rng: np.random.Generator) -> None:
        self.cfg = cfg
        self.loc = loc
        self.rng = rng
        self.overrides = WeatherOverrides()
        self._s = _Stochastic(cloud=cfg.cloud_mean, wind_ms=cfg.wind_mean_ms)
        self.state = self._compute(hour=0.0, day_of_year=80)

    # -- stochastic processes --------------------------------------------------------------

    def _ou(self, x: float, mean: float, tau: float, sd: float, dt: float) -> float:
        """Ornstein-Uhlenbeck step with stationary standard deviation `sd`."""
        sigma = sd * math.sqrt(2 / tau)
        return x + (mean - x) * dt / tau + sigma * math.sqrt(dt) * self.rng.standard_normal()

    def _advance_stochastic(self, dt: float) -> None:
        s, c = self._s, self.cfg
        s.cloud = min(
            1.0, max(0.0, self._ou(s.cloud, c.cloud_mean, self.CLOUD_TAU_S, c.cloud_volatility, dt))
        )
        s.wind_ms = max(
            0.0,
            self._ou(s.wind_ms, c.wind_mean_ms, self.WIND_TAU_S, 0.3 * c.wind_mean_ms + 0.1, dt),
        )
        if s.rain_remaining_s > 0:
            s.rain_remaining_s = max(0.0, s.rain_remaining_s - dt)
        else:
            # Rain is more likely under heavy cloud.
            p_hour = c.rain_probability_per_hour * min(2.0, s.cloud / max(c.cloud_mean, 0.05))
            p_step = 1 - (1 - min(p_hour, 1.0)) ** (dt / 3600)
            if self.rng.random() < p_step:
                s.rain_remaining_s = c.rain_duration_h * 3600

    def step(self, dt: float, hour: float, day_of_year: int) -> WeatherState:
        self._advance_stochastic(dt)
        raining = self._rain_rate() > 0
        target = self.RAIN_COOLING_C if raining else 0.0
        self._s.rain_cooling_c += (target - self._s.rain_cooling_c) * dt / self.RAIN_COOLING_TAU_S
        self.state = self._compute(hour, day_of_year)
        return self.state

    # -- deterministic part ----------------------------------------------------------------

    def _rain_rate(self) -> float:
        if self.overrides.rain_mm_h is not None:
            return self.overrides.rain_mm_h
        return self.cfg.rain_intensity_mm_h if self._s.rain_remaining_s > 0 else 0.0

    def _compute(self, hour: float, day_of_year: int) -> WeatherState:
        c, o = self.cfg, self.overrides
        rain = self._rain_rate()
        cloud = o.cloud if o.cloud is not None else self._s.cloud
        if rain > 0:
            cloud = max(cloud, 0.9)

        solar_h = solar_time_h(hour, day_of_year, self.loc)
        cos_z = sun_cos_zenith(solar_h, day_of_year, self.loc.latitude_deg)
        clear = clear_sky_ghi(cos_z)
        ghi = clear * cloud_transmission(cloud)

        # Diurnal temperature: minimum near sunrise, maximum ~14:30 solar time.
        # Cloud damps the swing (less daytime heating, less night-time radiative cooling).
        amplitude = c.temp_amplitude_c * (1 - 0.6 * cloud)
        temp = (
            c.temp_mean_c
            + o.temp_offset_c
            + amplitude * math.cos(2 * math.pi * (solar_h - 14.5) / 24)
            - self._s.rain_cooling_c
        )

        dew = c.dewpoint_c + o.dewpoint_offset_c
        if rain > 0:
            dew = max(dew, temp - 1.0)
        dew = min(dew, temp - 0.2)
        e = psychro.saturation_vapour_pressure(dew)
        rh = 100 * e / psychro.saturation_vapour_pressure(temp)

        wind = o.wind_ms if o.wind_ms is not None else self._s.wind_ms
        return WeatherState(
            temp_c=temp,
            dewpoint_c=dew,
            rh_pct=rh,
            chi=psychro.vapour_pressure_to_concentration(e, temp),
            solar_w_m2=ghi,
            clear_sky_w_m2=clear,
            sun_elevation_deg=math.degrees(math.asin(max(-1.0, min(1.0, cos_z)))),
            cloud=cloud,
            wind_ms=wind,
            rain_mm_h=rain,
            co2_ppm=c.co2_outside_ppm,
        )
