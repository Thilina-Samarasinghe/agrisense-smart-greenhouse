"""Lumped physics model of one greenhouse zone.

Each zone is treated as a single well-mixed volume of air above a crop canopy and a soil root
zone. State variables are integrated with explicit Euler in fixed sub-steps (<= 10 s, which is
well below the fastest time constant of roughly one minute for a fully ventilated zone).

Sub-models
----------
* Radiation: cover transmission, canopy/soil partition by Beer's law (k = 0.7).
* Transpiration: Stanghellini form of Penman-Monteith (LAI-scaled), with Jarvis-type stomatal
  response to light and FAO-56 water-stress coefficient Ks.
* Air energy balance: absorbed radiation, latent cooling, cover conduction (U-value),
  ventilation, soil exchange, lamps, heater, misting, condensation.
* Vapour balance: transpiration, soil evaporation, misting, ventilation, cover condensation.
* CO2 balance: canopy photosynthesis (rectangular hyperbola), respiration, ventilation.
* Soil water: FAO-56 root-zone balance with drainage above field capacity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from agrisense_core.config import CropStage, GreenhouseConfig, ZoneConfig
from agrisense_core.sim import psychro
from agrisense_core.sim.weather import WeatherState

# Radiation conversions
PAR_UMOL_PER_W_GLOBAL = 2.06  # umol/m2/s PAR per W/m2 of global solar radiation (~45 % PAR)
LUX_PER_W_GLOBAL = 110.0  # luminous efficacy of daylight
LUX_PER_UMOL_LED = 70.0  # typical full-spectrum white LED
J_PER_UMOL_PAR = 0.218  # radiant energy of 1 umol PAR photons

# Canopy and exchange coefficients
K_EXTINCTION = 0.7
NET_RADIATION_FRACTION = 0.75  # canopy net radiation / absorbed short-wave (long-wave losses)
RA_STILL_AIR = 220.0  # s/m canopy aerodynamic resistance in still greenhouse air
COVER_MASS_TRANSFER = 0.0025  # m/s, Lewis analogy with h ~ 3 W/m2K
COVER_TEMP_WEIGHT = 0.35  # cover temperature = T_out + w * (T_in - T_out)
CONDENSATION_HEAT_TO_AIR = 0.5  # share of condensation latent heat returned to the air
SOIL_AIR_H = 5.0  # W/m2K soil surface to air
SOIL_DEEP_K = 1.5  # W/m2K top soil to deep soil
SOIL_HEAT_CAPACITY = 2.5e5  # J/m2K for the top 10 cm
DRAINAGE_RATE = 1 / 3600  # 1/s, fraction of excess above field capacity drained per second

# Photosynthesis
QUANTUM_EFFICIENCY = 0.05  # mol CO2 per mol absorbed photons
CO2_COMPENSATION_PPM = 50.0
CO2_HALF_SAT_PPM = 400.0
RESPIRATION_FRACTION = 0.08  # dark respiration at 20 degC as a fraction of Pmax


@dataclass
class ZoneInputs:
    """Physical effect of the equipment during one step (already includes start-up delays)."""

    fan_flow_m3s: float = 0.0
    irrigation_lps: float = 0.0
    lamp_ppfd: float = 0.0
    lamp_power_w: float = 0.0
    mist_lps: float = 0.0
    heater_w: float = 0.0


@dataclass
class ZoneState:
    temp_c: float
    chi: float  # absolute humidity kg/m3
    co2_ppm: float
    vwc: float  # volumetric water content m3/m3
    soil_temp_c: float

    # Diagnostics (updated every step)
    rh_pct: float = 0.0
    vpd_kpa: float = 0.0
    par_umol: float = 0.0
    lux: float = 0.0
    inside_solar_w_m2: float = 0.0
    transpiration_mm_h: float = 0.0
    photosynthesis_umol: float = 0.0
    water_stress_ks: float = 1.0
    ventilation_ach: float = 0.0
    condensing: bool = False

    # Daily accumulators (reset at local midnight)
    dli_mol: float = 0.0
    et_mm_today: float = 0.0

    # Lifetime water accounting, litres
    totals: dict[str, float] = field(
        default_factory=lambda: {"irrigation_l": 0.0, "et_l": 0.0, "drainage_l": 0.0, "mist_l": 0.0}
    )


class ZoneModel:
    def __init__(self, zone: ZoneConfig, crop: CropStage, gh: GreenhouseConfig) -> None:
        self.cfg = zone
        self.crop = crop
        self.gh = gh
        self.area = zone.floor_area_m2
        self.volume = zone.volume_m3
        self.cover_area = zone.cover_area_m2
        self.pressure = psychro.atmospheric_pressure(gh.location.elevation_m)
        self.gamma = psychro.psychrometric_constant(self.pressure)
        self.canopy_fraction = 1 - math.exp(-K_EXTINCTION * crop.lai)
        self.state: ZoneState | None = None

    # ------------------------------------------------------------------ initial conditions

    def initialise(self, weather: WeatherState) -> ZoneState:
        self.state = ZoneState(
            temp_c=weather.temp_c,
            chi=weather.chi,
            co2_ppm=weather.co2_ppm,
            vwc=self.cfg.initial_vwc,
            soil_temp_c=self.gh.weather.temp_mean_c,
        )
        self._update_diagnostics(weather, ZoneInputs())
        return self.state

    # ------------------------------------------------------------------ helpers

    def leakage_m3s(self, wind_ms: float) -> float:
        s = self.gh.structure
        ach = s.leakage_ach + s.wind_leakage_ach_per_ms * wind_ms
        return ach * self.volume / 3600

    def water_stress(self, vwc: float) -> float:
        """FAO-56 Ks from root-zone depletion."""
        soil, zr = self.cfg.soil, self.crop.root_depth_m
        taw = 1000 * (soil.field_capacity - soil.wilting_point) * zr
        depletion = 1000 * (soil.field_capacity - vwc) * zr
        raw = self.crop.depletion_p * taw
        if depletion <= raw:
            return 1.0
        return max(0.0, min(1.0, (taw - depletion) / ((1 - self.crop.depletion_p) * taw)))

    def _update_diagnostics(self, w: WeatherState, u: ZoneInputs) -> None:
        s = self.state
        s.rh_pct = min(100.0, psychro.relative_humidity(s.chi, s.temp_c))
        s.vpd_kpa = psychro.vpd(s.chi, s.temp_c)
        s.inside_solar_w_m2 = w.solar_w_m2 * self.gh.cover.transmissivity
        s.par_umol = s.inside_solar_w_m2 * PAR_UMOL_PER_W_GLOBAL + u.lamp_ppfd
        s.lux = s.inside_solar_w_m2 * LUX_PER_W_GLOBAL + u.lamp_ppfd * LUX_PER_UMOL_LED

    # ------------------------------------------------------------------ main step

    def step(self, dt: float, w: WeatherState, u: ZoneInputs) -> ZoneState:
        s, cfg, crop, gh = self.state, self.cfg, self.crop, self.gh
        if s is None:
            raise RuntimeError("call initialise() first")
        A, V = self.area, self.volume
        T, chi = s.temp_c, s.chi
        rho = psychro.air_density(T, self.pressure)
        rho_cp = rho * psychro.CP_AIR
        L = psychro.LATENT_HEAT

        # --- radiation --------------------------------------------------------------
        inside_solar = w.solar_w_m2 * gh.cover.transmissivity
        absorbed = inside_solar * gh.cover.absorbed_fraction
        lamp_radiant = u.lamp_ppfd * J_PER_UMOL_PAR  # W/m2 PAR at canopy
        canopy_absorbed = self.canopy_fraction * (absorbed + lamp_radiant)
        rn_canopy = NET_RADIATION_FRACTION * canopy_absorbed
        # The remainder is re-radiated to benches, structure and cover, which warm the air.
        structure_heat = canopy_absorbed - rn_canopy
        rad_soil = (1 - self.canopy_fraction) * absorbed

        # --- ventilation ------------------------------------------------------------
        q_vent = self.leakage_m3s(w.wind_ms) + u.fan_flow_m3s
        ach = q_vent * 3600 / V
        ra = RA_STILL_AIR / (1 + 0.005 * ach)  # fans only modestly raise in-canopy air speed

        # --- transpiration (W/m2 ground) -------------------------------------------
        ks = self.water_stress(s.vwc)
        vpd = psychro.vpd(chi, T)
        delta = psychro.svp_slope(T)
        light_for_stomata = inside_solar + u.lamp_ppfd / PAR_UMOL_PER_W_GLOBAL
        rs = crop.rs_min_s_m * (1 + 150 / (light_for_stomata + 2))
        le_canopy = (delta * rn_canopy + 2 * crop.lai * rho_cp * vpd / ra) / (
            delta + self.gamma * (1 + rs / ra)
        )
        le_canopy = max(0.0, le_canopy) * ks  # FAO-56: ETc,adj = Ks * ETc

        # Soil evaporation from the exposed fraction, limited by surface wetness.
        wetness = (s.vwc - cfg.soil.wilting_point) / (
            cfg.soil.field_capacity - cfg.soil.wilting_point
        )
        le_soil = max(0.0, 0.3 * rad_soil * min(1.0, max(0.0, wetness)))

        et_kg_m2s = (le_canopy + le_soil) / L

        # --- misting ----------------------------------------------------------------
        mist_kg_s = u.mist_lps  # 1 L water = 1 kg
        mist_evap_eff = min(1.0, vpd / 0.3)
        mist_evap_kg_s = mist_kg_s * mist_evap_eff

        # --- condensation on the cover --------------------------------------------
        t_cover = w.temp_c + COVER_TEMP_WEIGHT * (T - w.temp_c)
        chi_sat_cover = psychro.saturation_concentration(t_cover)
        cond_kg_s = COVER_MASS_TRANSFER * self.cover_area * max(0.0, chi - chi_sat_cover)

        # --- air energy balance (W) -------------------------------------------------
        heat = (
            (rn_canopy - le_canopy + structure_heat) * A  # sensible heat from canopy and structure
            + SOIL_AIR_H * (s.soil_temp_c - T) * A
            - gh.cover.u_value_w_m2k * self.cover_area * (T - w.temp_c)
            - rho_cp * q_vent * (T - w.temp_c)
            + max(0.0, u.lamp_power_w - lamp_radiant * self.canopy_fraction * A)
            + u.heater_w
            - L * mist_evap_kg_s
            + CONDENSATION_HEAT_TO_AIR * L * cond_kg_s
        )
        capacity = rho_cp * V + gh.structure.thermal_mass_j_m2k * A
        T_new = T + heat / capacity * dt

        # --- vapour balance (kg/m3) -------------------------------------------------
        vapour_in = et_kg_m2s * A + mist_evap_kg_s
        vapour_out = q_vent * (chi - w.chi) + cond_kg_s
        chi_new = chi + (vapour_in - vapour_out) / V * dt
        chi_sat = psychro.saturation_concentration(T_new)
        fog = max(0.0, chi_new - chi_sat)  # supersaturation condenses as fog/droplets
        chi_new -= fog
        chi_new = max(chi_new, 1e-4)

        # --- CO2 balance (ppm) ------------------------------------------------------
        par = inside_solar * PAR_UMOL_PER_W_GLOBAL + u.lamp_ppfd
        absorbed_par = self.canopy_fraction * par
        c = s.co2_ppm
        f_co2 = ((c - CO2_COMPENSATION_PPM) / (c - CO2_COMPENSATION_PPM + CO2_HALF_SAT_PPM)) / (
            (420 - CO2_COMPENSATION_PPM) / (420 - CO2_COMPENSATION_PPM + CO2_HALF_SAT_PPM)
        )
        f_co2 = max(0.0, min(2.0, f_co2))
        f_temp = math.exp(-(((T - 25) / 12) ** 2))
        pmax = crop.pmax_umol_m2s
        gross = (
            (QUANTUM_EFFICIENCY * absorbed_par * pmax) / (QUANTUM_EFFICIENCY * absorbed_par + pmax)
            if absorbed_par > 0
            else 0.0
        )
        gross *= f_co2 * f_temp * math.sqrt(ks)
        resp = RESPIRATION_FRACTION * pmax * self.canopy_fraction * 2 ** ((T - 20) / 10)
        n_air = psychro.molar_air_density(T, self.pressure)
        dc = (resp - gross) * A / (V * n_air) + q_vent / V * (w.co2_ppm - c)
        c_new = max(CO2_COMPENSATION_PPM, c + dc * dt)

        # --- soil water (FAO-56) ----------------------------------------------------
        zr_mm = 1000 * crop.root_depth_m
        irrigation_mm_s = u.irrigation_lps / A
        et_mm_s = et_kg_m2s
        drain_mm_s = max(0.0, s.vwc - cfg.soil.field_capacity) * zr_mm * DRAINAGE_RATE
        vwc_new = s.vwc + (irrigation_mm_s - et_mm_s - drain_mm_s) / zr_mm * dt
        runoff_mm = max(0.0, vwc_new - cfg.soil.saturation) * zr_mm
        vwc_new = min(vwc_new, cfg.soil.saturation)
        if vwc_new < 0.02:  # physically the crop would be dead long before this
            vwc_new = 0.02

        # --- soil temperature -------------------------------------------------------
        soil_heat = (
            rad_soil
            - le_soil
            + SOIL_AIR_H * (T - s.soil_temp_c)
            - SOIL_DEEP_K * (s.soil_temp_c - gh.weather.temp_mean_c)
        )
        ts_new = s.soil_temp_c + soil_heat / SOIL_HEAT_CAPACITY * dt

        # --- commit -----------------------------------------------------------------
        s.temp_c, s.chi, s.co2_ppm, s.vwc, s.soil_temp_c = T_new, chi_new, c_new, vwc_new, ts_new
        s.transpiration_mm_h = et_mm_s * 3600
        s.photosynthesis_umol = gross
        s.water_stress_ks = ks
        s.ventilation_ach = ach
        s.condensing = cond_kg_s > 1e-6 or fog > 0
        s.dli_mol += par * dt / 1e6
        s.et_mm_today += et_mm_s * dt
        s.totals["irrigation_l"] += u.irrigation_lps * dt
        s.totals["et_l"] += et_mm_s * A * dt
        s.totals["drainage_l"] += drain_mm_s * A * dt + runoff_mm * A
        s.totals["mist_l"] += mist_kg_s * dt
        self._update_diagnostics(w, u)
        return s

    def refresh_air(self) -> None:
        """Recompute humidity diagnostics after an external change to the air state."""
        s = self.state
        s.rh_pct = min(100.0, psychro.relative_humidity(s.chi, s.temp_c))
        s.vpd_kpa = psychro.vpd(s.chi, s.temp_c)

    def soil_water_l(self) -> float:
        """Water currently stored in the root zone, litres."""
        return self.state.vwc * self.crop.root_depth_m * self.area * 1000

    def reset_daily(self) -> None:
        self.state.dli_mol = 0.0
        self.state.et_mm_today = 0.0
