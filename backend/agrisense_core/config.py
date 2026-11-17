"""Typed configuration for greenhouses, crops and sensors, loaded from YAML.

Every physical value is validated here so the simulator never runs with impossible parameters
(for example a wilting point above field capacity).
"""

from __future__ import annotations

from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- greenhouse


class LocationConfig(_Model):
    latitude_deg: float = Field(ge=-66, le=66)
    longitude_deg: float = Field(ge=-180, le=180)
    utc_offset_hours: float = Field(ge=-12, le=14)
    elevation_m: float = 0.0


class SimulationConfig(_Model):
    start: datetime
    step_s: float = Field(default=1.0, gt=0, le=10)
    seed: int = 42


class WeatherConfig(_Model):
    temp_mean_c: float
    temp_amplitude_c: float = Field(ge=0, le=20)
    dewpoint_c: float
    cloud_mean: float = Field(ge=0, le=1)
    cloud_volatility: float = Field(ge=0, le=1)
    wind_mean_ms: float = Field(ge=0)
    rain_probability_per_hour: float = Field(ge=0, le=1)
    rain_intensity_mm_h: float = Field(ge=0)
    rain_duration_h: float = Field(gt=0)
    co2_outside_ppm: float = Field(gt=0)

    @model_validator(mode="after")
    def _dewpoint_below_min_temp(self) -> WeatherConfig:
        if self.dewpoint_c > self.temp_mean_c:
            raise ValueError("dewpoint_c must not exceed temp_mean_c")
        return self


class CoverConfig(_Model):
    material: str
    u_value_w_m2k: float = Field(gt=0, le=15)
    transmissivity: float = Field(gt=0, le=1)
    absorbed_fraction: float = Field(gt=0, le=1)


class StructureConfig(_Model):
    leakage_ach: float = Field(ge=0)
    wind_leakage_ach_per_ms: float = Field(ge=0)
    thermal_mass_j_m2k: float = Field(ge=0)


class TankConfig(_Model):
    id: str
    capacity_l: float = Field(gt=0)
    initial_level_pct: float = Field(ge=0, le=100)
    height_m: float = Field(gt=0)
    catchment_area_m2: float = Field(ge=0)
    catchment_efficiency: float = Field(ge=0, le=1)


class PumpConfig(_Model):
    id: str
    max_flow_lpm: float = Field(gt=0)
    power_w: float = Field(ge=0)
    startup_delay_s: float = Field(default=0, ge=0)


class SoilConfig(_Model):
    type: str
    field_capacity: float = Field(gt=0, lt=1)
    wilting_point: float = Field(gt=0, lt=1)
    saturation: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _ordered(self) -> SoilConfig:
        if not self.wilting_point < self.field_capacity < self.saturation:
            raise ValueError("need wilting_point < field_capacity < saturation")
        return self


class FanConfig(_Model):
    count: int = Field(ge=1)
    airflow_m3h: float = Field(gt=0)
    power_w: float = Field(ge=0)
    startup_delay_s: float = Field(default=0, ge=0)


class ValveConfig(_Model):
    power_w: float = Field(ge=0)
    startup_delay_s: float = Field(default=0, ge=0)


class EmitterConfig(_Model):
    count: int = Field(ge=1)
    flow_lph: float = Field(gt=0)


class GrowLightConfig(_Model):
    ppfd_umol_m2s: float = Field(gt=0)
    power_w: float = Field(ge=0)
    startup_delay_s: float = Field(default=0, ge=0)


class MisterConfig(_Model):
    flow_lph: float = Field(gt=0)
    power_w: float = Field(ge=0)
    startup_delay_s: float = Field(default=0, ge=0)


class HeaterConfig(_Model):
    power_w: float = Field(gt=0)
    startup_delay_s: float = Field(default=0, ge=0)


class EquipmentConfig(_Model):
    fan: FanConfig
    valve: ValveConfig
    emitters: EmitterConfig
    grow_light: GrowLightConfig | None = None
    mister: MisterConfig | None = None
    heater: HeaterConfig | None = None


class ZoneConfig(_Model):
    id: str
    name: str
    crop: str
    stage: str
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    initial_vwc: float = Field(gt=0, lt=1)
    soil: SoilConfig
    equipment: EquipmentConfig

    @property
    def floor_area_m2(self) -> float:
        return self.length_m * self.width_m

    @property
    def volume_m3(self) -> float:
        return self.floor_area_m2 * self.height_m

    @property
    def cover_area_m2(self) -> float:
        """Roof plus walls of a simple box-shaped zone (roof pitch adds ~10 %)."""
        roof = self.floor_area_m2 * 1.1
        walls = 2 * (self.length_m + self.width_m) * self.height_m
        return roof + walls


class GreenhouseConfig(_Model):
    name: str
    id: str
    location: LocationConfig
    simulation: SimulationConfig
    weather: WeatherConfig
    cover: CoverConfig
    structure: StructureConfig
    tank: TankConfig
    pump: PumpConfig
    zones: list[ZoneConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_zone_ids(self) -> GreenhouseConfig:
        ids = [z.id for z in self.zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone ids must be unique")
        return self


# --------------------------------------------------------------------------- crops

Range = tuple[float, float]


class CropStage(_Model):
    lai: float = Field(gt=0, le=8)
    root_depth_m: float = Field(gt=0, le=2)
    rs_min_s_m: float = Field(gt=0)
    depletion_p: float = Field(gt=0, lt=1)
    pmax_umol_m2s: float = Field(gt=0)


class CropTargets(_Model):
    temp_day_c: Range
    temp_night_c: Range
    rh_pct: Range
    vwc: Range
    dli_mol_m2d: Range
    co2_ppm: Range


class CropProfile(_Model):
    display_name: str
    stages: dict[str, CropStage]
    targets: CropTargets


# --------------------------------------------------------------------------- sensors

SensorModel = Literal[
    "sht31", "capacitive_soil", "ds18b20", "bh1750", "scd30", "jsn_sr04t", "yf_s201"
]


class SensorInstall(_Model):
    id: str
    model: SensorModel
    source: Literal["sim", "mqtt"] = "sim"
    sample_interval_s: float = Field(gt=0)
    calibration: dict[str, float] = Field(default_factory=dict)


class SensorLayout(_Model):
    zone: list[SensorInstall]
    greenhouse: list[SensorInstall]


# --------------------------------------------------------------------------- loading


class AgriSenseConfig(_Model):
    greenhouse: GreenhouseConfig
    crops: dict[str, CropProfile]
    sensors: SensorLayout

    @model_validator(mode="after")
    def _crops_exist(self) -> AgriSenseConfig:
        for zone in self.greenhouse.zones:
            crop = self.crops.get(zone.crop)
            if crop is None:
                raise ValueError(f"zone {zone.id}: unknown crop '{zone.crop}'")
            if zone.stage not in crop.stages:
                raise ValueError(f"zone {zone.id}: crop '{zone.crop}' has no stage '{zone.stage}'")
        return self

    def crop_stage(self, zone: ZoneConfig) -> CropStage:
        return self.crops[zone.crop].stages[zone.stage]


def _read_yaml(directory: Path | None, name: str) -> dict:
    if directory is not None:
        text = (directory / name).read_text(encoding="utf-8")
    else:
        text = resources.files("agrisense_core.profiles").joinpath(name).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def load_config(directory: str | Path | None = None) -> AgriSenseConfig:
    """Load greenhouse.yaml, crops.yaml and sensors.yaml from `directory` (default: built-ins)."""
    path = Path(directory) if directory is not None else None
    return AgriSenseConfig(
        greenhouse=_read_yaml(path, "greenhouse.yaml"),
        crops=_read_yaml(path, "crops.yaml"),
        sensors=_read_yaml(path, "sensors.yaml"),
    )
