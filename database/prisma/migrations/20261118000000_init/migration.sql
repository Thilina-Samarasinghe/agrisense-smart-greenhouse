-- CreateTable
CREATE TABLE "runs" (
    "id" SERIAL NOT NULL,
    "created_at" TIMESTAMP(6) NOT NULL,
    "seed" INTEGER NOT NULL,
    "sim_start" TIMESTAMP(6) NOT NULL,
    "greenhouse" VARCHAR(100) NOT NULL,

    CONSTRAINT "runs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "zone_states" (
    "id" SERIAL NOT NULL,
    "run_id" INTEGER NOT NULL,
    "ts" TIMESTAMP(6) NOT NULL,
    "zone_id" VARCHAR(20) NOT NULL,
    "temp_c" DOUBLE PRECISION NOT NULL,
    "rh_pct" DOUBLE PRECISION NOT NULL,
    "vpd_kpa" DOUBLE PRECISION NOT NULL,
    "co2_ppm" DOUBLE PRECISION NOT NULL,
    "vwc" DOUBLE PRECISION NOT NULL,
    "soil_temp_c" DOUBLE PRECISION NOT NULL,
    "par_umol" DOUBLE PRECISION NOT NULL,
    "dli_mol" DOUBLE PRECISION NOT NULL,
    "et_mm_h" DOUBLE PRECISION NOT NULL,
    "measured_temp_c" DOUBLE PRECISION,
    "measured_rh_pct" DOUBLE PRECISION,
    "measured_vwc_pct" DOUBLE PRECISION,
    "measured_lux" DOUBLE PRECISION,
    "fan" DOUBLE PRECISION NOT NULL,
    "valve" DOUBLE PRECISION NOT NULL,
    "light" DOUBLE PRECISION NOT NULL,
    "mister" DOUBLE PRECISION NOT NULL,
    "irrigation_l_total" DOUBLE PRECISION NOT NULL,
    "et_l_total" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "zone_states_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "greenhouse_states" (
    "id" SERIAL NOT NULL,
    "run_id" INTEGER NOT NULL,
    "ts" TIMESTAMP(6) NOT NULL,
    "out_temp_c" DOUBLE PRECISION NOT NULL,
    "out_rh_pct" DOUBLE PRECISION NOT NULL,
    "solar_w_m2" DOUBLE PRECISION NOT NULL,
    "cloud" DOUBLE PRECISION NOT NULL,
    "wind_ms" DOUBLE PRECISION NOT NULL,
    "rain_mm_h" DOUBLE PRECISION NOT NULL,
    "tank_pct" DOUBLE PRECISION NOT NULL,
    "tank_inflow_l_total" DOUBLE PRECISION NOT NULL,
    "alerts_active" INTEGER NOT NULL,

    CONSTRAINT "greenhouse_states_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "actuator_states" (
    "id" SERIAL NOT NULL,
    "run_id" INTEGER NOT NULL,
    "ts" TIMESTAMP(6) NOT NULL,
    "actuator_id" VARCHAR(40) NOT NULL,
    "kind" VARCHAR(20) NOT NULL,
    "zone_id" VARCHAR(20),
    "level" DOUBLE PRECISION NOT NULL,
    "energy_wh_total" DOUBLE PRECISION NOT NULL,
    "runtime_s_total" DOUBLE PRECISION NOT NULL,
    "starts_total" INTEGER NOT NULL,

    CONSTRAINT "actuator_states_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sensor_readings" (
    "id" SERIAL NOT NULL,
    "run_id" INTEGER NOT NULL,
    "ts" TIMESTAMP(6) NOT NULL,
    "sensor_id" VARCHAR(40) NOT NULL,
    "zone_id" VARCHAR(20),
    "quantity" VARCHAR(30) NOT NULL,
    "value" DOUBLE PRECISION,
    "raw" DOUBLE PRECISION,
    "unit" VARCHAR(12) NOT NULL,
    "quality" VARCHAR(12) NOT NULL,

    CONSTRAINT "sensor_readings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "decisions" (
    "id" SERIAL NOT NULL,
    "run_id" INTEGER NOT NULL,
    "ts" TIMESTAMP(6) NOT NULL,
    "actuator_id" VARCHAR(40) NOT NULL,
    "zone_id" VARCHAR(20),
    "from_level" DOUBLE PRECISION NOT NULL,
    "to_level" DOUBLE PRECISION NOT NULL,
    "rule" VARCHAR(40) NOT NULL,
    "source" VARCHAR(20) NOT NULL,
    "message" TEXT NOT NULL,

    CONSTRAINT "decisions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "alerts" (
    "id" SERIAL NOT NULL,
    "run_id" INTEGER NOT NULL,
    "alert_id" INTEGER NOT NULL,
    "code" VARCHAR(40) NOT NULL,
    "severity" VARCHAR(10) NOT NULL,
    "message" TEXT NOT NULL,
    "zone_id" VARCHAR(20),
    "subject" VARCHAR(60),
    "latched" BOOLEAN NOT NULL,
    "raised_at" TIMESTAMP(6) NOT NULL,
    "cleared_at" TIMESTAMP(6),

    CONSTRAINT "alerts_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ix_zone_states_run_zone_ts" ON "zone_states"("run_id", "zone_id", "ts");

-- CreateIndex
CREATE INDEX "ix_greenhouse_states_run_ts" ON "greenhouse_states"("run_id", "ts");

-- CreateIndex
CREATE INDEX "ix_actuator_states_run_ts" ON "actuator_states"("run_id", "ts");

-- CreateIndex
CREATE INDEX "ix_sensor_readings_run_sensor_ts" ON "sensor_readings"("run_id", "sensor_id", "ts");

-- CreateIndex
CREATE INDEX "ix_decisions_run_ts" ON "decisions"("run_id", "ts");

-- CreateIndex
CREATE UNIQUE INDEX "ix_alerts_run_alert" ON "alerts"("run_id", "alert_id");

-- AddForeignKey
ALTER TABLE "zone_states" ADD CONSTRAINT "zone_states_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "greenhouse_states" ADD CONSTRAINT "greenhouse_states_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "actuator_states" ADD CONSTRAINT "actuator_states_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "sensor_readings" ADD CONSTRAINT "sensor_readings_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "decisions" ADD CONSTRAINT "decisions_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE NO ACTION;

-- AddForeignKey
ALTER TABLE "alerts" ADD CONSTRAINT "alerts_run_id_fkey" FOREIGN KEY ("run_id") REFERENCES "runs"("id") ON DELETE CASCADE ON UPDATE NO ACTION;
