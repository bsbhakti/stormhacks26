"""TimescaleDB persistence for wearable health readings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from dotenv import load_dotenv
import psycopg
from psycopg.types.json import Jsonb


load_dotenv("tiger-cloud-stormhacks-db-credentials.env")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.health_readings (
    recorded_at TIMESTAMPTZ NOT NULL,
    patient_id TEXT NOT NULL,
    device_id TEXT,
    heart_rate_bpm DOUBLE PRECISION,
    spo2_percent DOUBLE PRECISION,
    temperature_c DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (patient_id, recorded_at)
);

SELECT create_hypertable(
    'public.health_readings',
    by_range('recorded_at'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS health_readings_patient_time_idx
    ON public.health_readings (patient_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS public.ecg_samples (
    recorded_at TIMESTAMPTZ NOT NULL,
    patient_id TEXT NOT NULL,
    sample_index INTEGER NOT NULL,
    sample_value DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (patient_id, recorded_at, sample_index)
);

SELECT create_hypertable(
    'public.ecg_samples',
    by_range('recorded_at'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS ecg_samples_patient_time_idx
    ON public.ecg_samples (patient_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS public.patient_feature_snapshots (
    calculated_at TIMESTAMPTZ NOT NULL,
    patient_id TEXT NOT NULL,
    features JSONB NOT NULL,
    category_scores JSONB NOT NULL,
    patient_score DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (patient_id, calculated_at)
);

SELECT create_hypertable(
    'public.patient_feature_snapshots',
    by_range('calculated_at'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS patient_feature_snapshots_patient_time_idx
    ON public.patient_feature_snapshots (patient_id, calculated_at DESC);
"""


@dataclass(frozen=True)
class HealthReading:
    """One timestamped sample received from a wearable."""

    patient_id: str
    recorded_at: datetime
    device_id: str | None = None
    heart_rate_bpm: float | None = None
    spo2_percent: float | None = None
    temperature_c: float | None = None
    ecg: list[float] | None = None
    metadata: Mapping[str, Any] | None = None

    def as_row(self) -> tuple[Any, ...]:
        """Return values in the same order as the insert statement."""
        return (
            self.recorded_at,
            self.patient_id,
            self.device_id,
            self.heart_rate_bpm,
            self.spo2_percent,
            self.temperature_c,
            Jsonb(dict(self.metadata or {})),
        )


def database_url() -> str:
    """Read the database URL without providing a credential fallback."""
    value = os.environ.get("TIMESCALE_SERVICE_URL")
    if not value:
        raise RuntimeError(
            "TIMESCALE_SERVICE_URL is not set; configure it in the server environment"
        )
    return value


def connect() -> psycopg.Connection[Any]:
    """Open a TLS PostgreSQL connection to Tiger Cloud."""
    return psycopg.connect(database_url())


def initialize_schema() -> None:
    """Create the raw-reading table and hypertable if they do not exist."""
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)


def write_reading(reading: HealthReading) -> None:
    """Insert vitals and their ECG samples in one transaction."""
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.health_readings (
                    recorded_at,
                    patient_id,
                    device_id,
                    heart_rate_bpm,
                    spo2_percent,
                    temperature_c,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (patient_id, recorded_at) DO UPDATE SET
                    device_id = EXCLUDED.device_id,
                    heart_rate_bpm = EXCLUDED.heart_rate_bpm,
                    spo2_percent = EXCLUDED.spo2_percent,
                    temperature_c = EXCLUDED.temperature_c,
                    metadata = EXCLUDED.metadata
                """,
                reading.as_row(),
            )
            if reading.ecg:
                cursor.executemany(
                    """
                    INSERT INTO public.ecg_samples (
                        recorded_at,
                        patient_id,
                        sample_index,
                        sample_value
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (patient_id, recorded_at, sample_index)
                    DO UPDATE SET sample_value = EXCLUDED.sample_value
                    """,
                    [
                        (
                            reading.recorded_at + timedelta(seconds=index / 250),
                        reading.patient_id,
                        index,
                        sample,
                        )
                    for index, sample in enumerate(reading.ecg)
                    ]
                )


def reading_from_payload(payload: Mapping[str, Any]) -> HealthReading:
    """Validate and normalize the JSON body sent by the wearable/router."""
    patient_id = payload.get("patient_id")
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("patient_id must be a non-empty string")

    recorded_at = payload.get("recorded_at")
    if recorded_at is None:
        timestamp = datetime.now(timezone.utc)
    elif isinstance(recorded_at, str):
        try:
            timestamp = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("recorded_at must be an ISO-8601 timestamp") from error
        if timestamp.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        timestamp = timestamp.astimezone(timezone.utc)
    else:
        raise ValueError("recorded_at must be an ISO-8601 timestamp")

    def optional_number(name: str) -> float | None:
        value = payload.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        return float(value)

    device_id = payload.get("device_id")
    if device_id is not None and (
        not isinstance(device_id, str) or not device_id.strip()
    ):
        raise ValueError("device_id must be a non-empty string when provided")

    ecg = payload.get("ecg")
    if ecg is not None:
        if not isinstance(ecg, list) or any(
            isinstance(sample, bool) or not isinstance(sample, (int, float))
            for sample in ecg
        ):
            raise ValueError("ecg must be an array of numbers")
        ecg = [float(sample) for sample in ecg]

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a JSON object")

    return HealthReading(
        patient_id=patient_id.strip(),
        recorded_at=timestamp,
        device_id=device_id,
        heart_rate_bpm=optional_number("heart_rate_bpm"),
        spo2_percent=optional_number("spo2_percent"),
        temperature_c=optional_number("temperature_c"),
        ecg=ecg,
        metadata=metadata,
    )


def payload_to_json(reading: HealthReading) -> str:
    """Provide a JSON representation useful for logs or local testing."""
    return json.dumps(
        {
            "patient_id": reading.patient_id,
            "recorded_at": reading.recorded_at.isoformat(),
            "device_id": reading.device_id,
            "heart_rate_bpm": reading.heart_rate_bpm,
            "spo2_percent": reading.spo2_percent,
            "temperature_c": reading.temperature_c,
            "ecg_samples": reading.ecg,
            "metadata": reading.metadata or {},
        }
    )
