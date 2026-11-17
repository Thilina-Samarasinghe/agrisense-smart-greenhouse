import numpy as np
import pytest

from agrisense_core.sim import weather as wx


def test_equinox_noon_sun_is_nearly_overhead_in_colombo(config):
    loc = config.greenhouse.location
    cos_z = wx.sun_cos_zenith(12.0, 80, loc.latitude_deg)
    assert np.degrees(np.arccos(cos_z)) == pytest.approx(6.9, abs=1.5)


def test_no_sun_at_midnight(config):
    assert wx.clear_sky_ghi(wx.sun_cos_zenith(0.0, 80, 6.9)) == 0.0


def test_daily_clear_sky_energy_is_realistic(config):
    loc = config.greenhouse.location
    total = 0.0
    for minute in range(24 * 60):
        h = wx.solar_time_h(minute / 60, 80, loc)
        total += wx.clear_sky_ghi(wx.sun_cos_zenith(h, 80, loc.latitude_deg)) * 60
    kwh = total / 3.6e6
    assert 6.0 < kwh < 9.0  # tropical clear-sky day: ~7-8 kWh/m2


def test_temperature_cycle_and_rain(config):
    rng = np.random.default_rng(0)
    m = wx.WeatherModel(config.greenhouse.weather, config.greenhouse.location, rng)
    m.overrides.cloud = 0.0
    dawn = m.step(60, 6.0, 80).temp_c
    afternoon = m.step(60, 14.5, 80).temp_c
    assert afternoon - dawn > 4
    m.overrides.rain_mm_h = 10
    s = m.step(60, 14.5, 80)
    assert s.rain_mm_h == 10 and s.cloud >= 0.9 and s.rh_pct > 90


def test_weather_is_reproducible(config):
    def series(seed):
        m = wx.WeatherModel(
            config.greenhouse.weather, config.greenhouse.location, np.random.default_rng(seed)
        )
        return [m.step(60, (i / 60) % 24, 80).cloud for i in range(600)]

    assert series(3) == series(3)
    assert series(3) != series(4)
