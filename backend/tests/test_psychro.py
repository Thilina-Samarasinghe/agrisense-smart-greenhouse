import pytest

from agrisense_core.sim import psychro


def test_saturation_vapour_pressure_matches_fao56_tables():
    assert psychro.saturation_vapour_pressure(20) == pytest.approx(2.338, abs=0.002)
    assert psychro.saturation_vapour_pressure(30) == pytest.approx(4.243, abs=0.003)


def test_slope_matches_fao56_table():
    assert psychro.svp_slope(25) == pytest.approx(0.189, abs=0.001)


def test_rh_roundtrip_and_vpd():
    chi = psychro.concentration_from_rh(60, 28)
    assert psychro.relative_humidity(chi, 28) == pytest.approx(60, rel=1e-6)
    assert psychro.vpd(chi, 28) == pytest.approx(0.4 * psychro.saturation_vapour_pressure(28))


def test_dewpoint_inverse():
    e = psychro.saturation_vapour_pressure(18.0)
    assert psychro.dewpoint(e) == pytest.approx(18.0, abs=1e-6)


def test_pressure_at_altitude():
    assert psychro.atmospheric_pressure(0) == pytest.approx(101.3, abs=0.1)
    assert psychro.atmospheric_pressure(1800) == pytest.approx(81.8, abs=0.3)
