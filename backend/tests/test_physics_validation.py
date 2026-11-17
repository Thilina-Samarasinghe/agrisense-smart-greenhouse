"""Validate the greenhouse model against known real-world behaviour."""

import pytest

from agrisense_core.sim.engine import GreenhouseEngine


def _mean(values):
    return sum(values) / len(values)


def _midday(series):
    return [v for h, v in series if 11 <= h <= 14]


def test_closed_greenhouse_heats_10_to_20_K_above_outside_at_midday(closed_day):
    _, rise, _ = closed_day
    peak = max(_midday(rise))
    assert 10 <= peak <= 20


def test_fan_ventilation_keeps_zone_close_to_outside(ventilated_day):
    _, rise, _ = ventilated_day
    peak = max(_midday(rise))
    assert 0.5 <= peak <= 4.0


def test_night_is_slightly_warmer_than_outside_and_more_humid_than_day(ventilated_day):
    _, rise, rh = ventilated_day
    night_rise = [v for h, v in rise if 1 <= h <= 4]
    assert all(-0.5 < v < 3 for v in night_rise)
    night_rh = _mean([v for h, v in rh if 1 <= h <= 4])
    day_rh = _mean([v for h, v in rh if 12 <= h <= 14])
    assert night_rh > day_rh + 5


@pytest.mark.parametrize(
    ("zone", "low", "high"), [("A", 3.0, 6.5), ("B", 3.0, 6.0), ("C", 2.0, 5.0)]
)
def test_daily_crop_water_use_is_realistic(ventilated_day, zone, low, high):
    e, _, _ = ventilated_day
    assert low <= e.zones[zone].state.et_mm_today <= high


def test_closed_greenhouse_reduces_transpiration_vs_ventilated(closed_day, ventilated_day):
    closed = closed_day[0].zones["A"].state.et_mm_today
    vent = ventilated_day[0].zones["A"].state.et_mm_today
    assert closed < vent


def test_photosynthesis_draws_co2_below_outside_in_ventilated_daylight(config):
    e = GreenhouseEngine(config, seed=2, step_s=10.0)
    e.weather.overrides.cloud = 0.1
    e.run_for(9.5 * 3600)  # 09:30, moderate temperature, fans off
    assert e.zones["A"].state.co2_ppm < config.greenhouse.weather.co2_outside_ppm


def test_night_respiration_raises_co2(config):
    e = GreenhouseEngine(config, seed=2, step_s=10.0)
    e.run_for(4 * 3600)
    assert e.zones["A"].state.co2_ppm > config.greenhouse.weather.co2_outside_ppm + 20


def test_dli_inside_is_reduced_by_cover(ventilated_day):
    e, _, _ = ventilated_day
    dli = e.zones["C"].state.dli_mol
    assert 25 < dli < 55  # clear tropical day ~55-60 mol outside, x0.75 cover


def test_water_stress_reduces_transpiration(config):
    def midday_et(vwc):
        e = GreenhouseEngine(config, seed=3, step_s=10.0)
        e.weather.overrides.cloud = 0.1
        e.zones["A"].state.vwc = vwc
        e.run_for(12 * 3600)
        return e.zones["A"].state.transpiration_mm_h, e.zones["A"].state.water_stress_ks

    wet_et, wet_ks = midday_et(0.30)
    dry_et, dry_ks = midday_et(0.14)
    assert wet_ks == 1.0 and dry_ks < 0.3
    assert dry_et < 0.5 * wet_et


def test_soil_drains_toward_field_capacity(config):
    e = GreenhouseEngine(config, seed=3, step_s=10.0)
    zone = e.zones["A"]
    zone.state.vwc = zone.cfg.soil.saturation
    e.run_for(6 * 3600)  # night: almost no ET
    assert zone.cfg.soil.field_capacity <= zone.state.vwc < zone.cfg.soil.field_capacity + 0.03
