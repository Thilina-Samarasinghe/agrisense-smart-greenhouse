"""Application settings, loaded from environment variables (prefix AGRISENSE_) or backend/.env."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGRISENSE_", extra="ignore")

    app_name: str = "AgriSense"
    environment: str = "development"
    # SQLite for development; switch to PostgreSQL later by changing only this URL.
    database_url: str = "sqlite:///./agrisense.db"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Simulation service
    autostart: bool = True  # run the simulation loop when the server starts
    config_dir: str | None = None  # folder with YAML profiles (default: built-in)
    seed: int | None = None
    sim_speed: float = Field(default=60.0, gt=0)  # simulated seconds per real second
    sim_step_s: float = Field(default=5.0, gt=0, le=10)
    loop_interval_s: float = Field(default=0.1, gt=0)  # real seconds between loop iterations
    max_steps_per_loop: int = Field(default=2000, gt=0)  # keeps the server responsive

    # Persistence (simulated seconds between stored snapshots)
    state_every_s: float = Field(default=60.0, gt=0)
    readings_every_s: float = Field(default=300.0, gt=0)
    keep_runs: int = Field(default=5, ge=1)  # older simulation runs are pruned on reset
    flush_every_s: float = Field(default=2.0, gt=0)  # real seconds between background writes
    retain_days: float = Field(default=30.0, gt=0)  # simulated days of history kept per run

    # Phase 4 models and reports (default: the repository's ml/ folder)
    ml_dir: str | None = None

    # Live WebSocket updates per real second
    ws_rate_hz: float = Field(default=2.0, gt=0, le=20)


settings = Settings()
