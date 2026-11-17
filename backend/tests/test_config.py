import pytest
from pydantic import ValidationError

from agrisense_core.config import SoilConfig


def test_default_profiles_load(config):
    gh = config.greenhouse
    assert [z.id for z in gh.zones] == ["A", "B", "C"]
    assert {z.crop for z in gh.zones} == {"tomato", "chilli", "lettuce"}
    assert config.crop_stage(gh.zones[0]).lai > 0
    assert len(config.sensors.zone) >= 5


def test_zone_geometry(config):
    z = config.greenhouse.zones[0]
    assert z.floor_area_m2 == 50
    assert z.volume_m3 == 150
    assert z.cover_area_m2 == pytest.approx(55 + 90)


def test_soil_must_be_ordered():
    with pytest.raises(ValidationError):
        SoilConfig(type="bad", field_capacity=0.1, wilting_point=0.2, saturation=0.4)
