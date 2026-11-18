"""Database tables. All `ts` columns are simulated (greenhouse local) time.

Every row belongs to a simulation run, so a reset starts a clean history while older runs stay
available for comparison until they are pruned.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)  # real wall-clock time
    seed: Mapped[int] = mapped_column(Integer)
    sim_start: Mapped[datetime] = mapped_column(DateTime)
    greenhouse: Mapped[str] = mapped_column(String(100))


class ZoneState(Base):
    """True physical state plus what the controller measured, per zone, per stored interval."""

    __tablename__ = "zone_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime)
    zone_id: Mapped[str] = mapped_column(String(20))
    temp_c: Mapped[float] = mapped_column(Float)
    rh_pct: Mapped[float] = mapped_column(Float)
    vpd_kpa: Mapped[float] = mapped_column(Float)
    co2_ppm: Mapped[float] = mapped_column(Float)
    vwc: Mapped[float] = mapped_column(Float)
    soil_temp_c: Mapped[float] = mapped_column(Float)
    par_umol: Mapped[float] = mapped_column(Float)
    dli_mol: Mapped[float] = mapped_column(Float)
    et_mm_h: Mapped[float] = mapped_column(Float)
    measured_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_rh_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_vwc_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_lux: Mapped[float | None] = mapped_column(Float, nullable=True)
    fan: Mapped[float] = mapped_column(Float, default=0)
    valve: Mapped[float] = mapped_column(Float, default=0)
    light: Mapped[float] = mapped_column(Float, default=0)
    mister: Mapped[float] = mapped_column(Float, default=0)
    irrigation_l_total: Mapped[float] = mapped_column(Float)
    et_l_total: Mapped[float] = mapped_column(Float)

    __table_args__ = (Index("ix_zone_states_run_zone_ts", "run_id", "zone_id", "ts"),)


class GreenhouseState(Base):
    __tablename__ = "greenhouse_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime)
    out_temp_c: Mapped[float] = mapped_column(Float)
    out_rh_pct: Mapped[float] = mapped_column(Float)
    solar_w_m2: Mapped[float] = mapped_column(Float)
    cloud: Mapped[float] = mapped_column(Float)
    wind_ms: Mapped[float] = mapped_column(Float)
    rain_mm_h: Mapped[float] = mapped_column(Float)
    tank_pct: Mapped[float] = mapped_column(Float)
    tank_inflow_l_total: Mapped[float] = mapped_column(Float)
    alerts_active: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("ix_greenhouse_states_run_ts", "run_id", "ts"),)


class ActuatorState(Base):
    __tablename__ = "actuator_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime)
    actuator_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))
    zone_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    level: Mapped[float] = mapped_column(Float)
    energy_wh_total: Mapped[float] = mapped_column(Float)
    runtime_s_total: Mapped[float] = mapped_column(Float)
    starts_total: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("ix_actuator_states_run_ts", "run_id", "ts"),)


class SensorReading(Base):
    """Raw sensor readings as the controller received them (sampled for storage)."""

    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime)
    sensor_id: Mapped[str] = mapped_column(String(40))
    zone_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[str] = mapped_column(String(30))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(12))
    quality: Mapped[str] = mapped_column(String(12))

    __table_args__ = (Index("ix_sensor_readings_run_sensor_ts", "run_id", "sensor_id", "ts"),)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime)
    actuator_id: Mapped[str] = mapped_column(String(40))
    zone_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    from_level: Mapped[float] = mapped_column(Float)
    to_level: Mapped[float] = mapped_column(Float)
    rule: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_decisions_run_ts", "run_id", "ts"),)


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    alert_id: Mapped[int] = mapped_column(Integer)  # id within the run
    code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    zone_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(60), nullable=True)
    latched: Mapped[bool] = mapped_column(default=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_alerts_run_alert", "run_id", "alert_id", unique=True),)
