"""Psychrometrics and physical constants (FAO-56 conventions).

Units: temperature in degC, pressure in kPa, vapour concentration in kg/m3.
"""

from __future__ import annotations

import math

CP_AIR = 1006.0  # J/(kg K) specific heat of air
R_UNIVERSAL = 8.314  # J/(mol K)
R_VAPOUR = 461.5  # J/(kg K) gas constant of water vapour
LATENT_HEAT = 2.45e6  # J/kg latent heat of vaporisation (~20 degC)
P_ATM_SEA = 101.325  # kPa
KELVIN = 273.15


def atmospheric_pressure(elevation_m: float) -> float:
    """FAO-56 eq. 7, kPa."""
    return P_ATM_SEA * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26


def psychrometric_constant(pressure_kpa: float) -> float:
    """FAO-56 eq. 8, kPa/K."""
    return 0.000665 * pressure_kpa


def saturation_vapour_pressure(temp_c: float) -> float:
    """Tetens equation (FAO-56 eq. 11), kPa."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def svp_slope(temp_c: float) -> float:
    """Slope of the saturation vapour pressure curve (FAO-56 eq. 13), kPa/K."""
    es = saturation_vapour_pressure(temp_c)
    return 4098.0 * es / (temp_c + 237.3) ** 2


def air_density(temp_c: float, pressure_kpa: float = P_ATM_SEA) -> float:
    """Dry-air density, kg/m3."""
    return pressure_kpa * 1000.0 / (287.05 * (temp_c + KELVIN))


def vapour_pressure_to_concentration(e_kpa: float, temp_c: float) -> float:
    """Ideal gas: absolute humidity in kg/m3."""
    return e_kpa * 1000.0 / (R_VAPOUR * (temp_c + KELVIN))


def concentration_to_vapour_pressure(chi: float, temp_c: float) -> float:
    return chi * R_VAPOUR * (temp_c + KELVIN) / 1000.0


def saturation_concentration(temp_c: float) -> float:
    return vapour_pressure_to_concentration(saturation_vapour_pressure(temp_c), temp_c)


def relative_humidity(chi: float, temp_c: float) -> float:
    """Relative humidity 0..100 % from absolute humidity."""
    e = concentration_to_vapour_pressure(chi, temp_c)
    return 100.0 * e / saturation_vapour_pressure(temp_c)


def concentration_from_rh(rh_pct: float, temp_c: float) -> float:
    return vapour_pressure_to_concentration(
        saturation_vapour_pressure(temp_c) * rh_pct / 100, temp_c
    )


def vpd(chi: float, temp_c: float) -> float:
    """Vapour pressure deficit, kPa (never negative)."""
    return max(
        0.0, saturation_vapour_pressure(temp_c) - concentration_to_vapour_pressure(chi, temp_c)
    )


def dewpoint(e_kpa: float) -> float:
    """Inverse Tetens, degC."""
    a = math.log(max(e_kpa, 1e-6) / 0.6108)
    return 237.3 * a / (17.27 - a)


def molar_air_density(temp_c: float, pressure_kpa: float = P_ATM_SEA) -> float:
    """mol/m3, used to convert umol CO2 per m3 into ppm."""
    return pressure_kpa * 1000.0 / (R_UNIVERSAL * (temp_c + KELVIN))
