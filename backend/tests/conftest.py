import pytest

from agrisense_core.config import load_config
from agrisense_core.sim.engine import GreenhouseEngine


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture
def engine(config):
    return GreenhouseEngine(config, seed=7, step_s=5.0)


def run_clear_day(config, fans_daytime: bool):
    """Simulate a clear day (cloud 0.1); return engine and per-step zone-A temperature rise."""
    e = GreenhouseEngine(config, seed=1, step_s=10.0)
    e.weather.overrides.cloud = 0.1
    rise, rh = [], []
    for _ in range(int(23.9 * 360)):
        if fans_daytime:
            level = 1.0 if 7 <= e.clock.hour_of_day < 18 else 0.0
            for z in e.zones:
                if e.actuators[f"{z}.fan"].commanded != level:
                    e.command(f"{z}.fan", level)
        e.step()
        rise.append((e.clock.hour_of_day, e.zones["A"].state.temp_c - e.weather.state.temp_c))
        rh.append((e.clock.hour_of_day, e.zones["A"].state.rh_pct))
    return e, rise, rh


@pytest.fixture(scope="session")
def closed_day(config):
    return run_clear_day(config, fans_daytime=False)


@pytest.fixture(scope="session")
def ventilated_day(config):
    return run_clear_day(config, fans_daytime=True)
