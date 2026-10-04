"""Compute triage-oriented wearable features and scores every five seconds.

The thresholds in this module are engineering defaults for a hackathon
prototype, not medical advice or a diagnostic system.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from timescale_db import connect, initialize_schema


SAMPLE_RATE_HZ = 250
WINDOW_10_SECONDS = timedelta(seconds=10)
WINDOW_30_SECONDS = timedelta(seconds=30)
RUN_INTERVAL_SECONDS = 5


@dataclass(frozen=True)
class VitalSample:
    recorded_at: datetime
    value: float


@dataclass(frozen=True)
class PipelineConfig:
    """Tunable prototype thresholds and score weights."""

    heart_rate_low: float = 50
    heart_rate_high: float = 120
    spo2_low: float = 94
    temperature_low: float = 35
    temperature_high: float = 38
    abnormal_duration_seconds: float = 10
    max_sample_gap_seconds: float = 5
    deteriorating_slope: float = 0.5
    ecg_irregularity_limit: float = 0.2
    ecg_signal_quality_limit: float = 0.8


FEATURE_NAMES = (
    "hr_current",
    "hr_mean_10s",
    "hr_slope_10s",
    "hr_abnormal_duration",
    "spo2_current",
    "spo2_mean_10s",
    "spo2_min_30s",
    "spo2_slope_10s",
    "spo2_low_duration",
    "temp_current",
    "temp_mean_30s",
    "temp_slope_30s",
    "ecg_hr",
    "rr_mean",
    "rr_std",
    "ecg_irregularity",
    "ecg_signal_quality",
    "num_abnormal_metrics",
    "num_deteriorating_metrics",
    "data_age",
)


def _mean(samples: Sequence[VitalSample]) -> float:
    return statistics.fmean(sample.value for sample in samples) if samples else math.nan


def _slope(samples: Sequence[VitalSample]) -> float:
    """Return units per second using least-squares linear regression."""
    if len(samples) < 2:
        return 0.0
    start = samples[0].recorded_at
    x_values = [(sample.recorded_at - start).total_seconds() for sample in samples]
    y_values = [sample.value for sample in samples]
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    denominator = sum((x - x_mean) ** 2 for x in x_values)
    return (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        / denominator
        if denominator
        else 0.0
    )


def _duration_above_or_below(
    samples: Sequence[VitalSample],
    condition: Any,
    max_sample_gap_seconds: float,
) -> float:
    """Estimate how long the latest consecutive abnormal run has lasted."""
    if not samples:
        return 0.0
    latest = samples[-1]
    if not condition(latest.value):
        return 0.0
    end = latest.recorded_at
    start = end
    newer = latest
    for sample in reversed(samples[:-1]):
        if not condition(sample.value):
            break
        if (
            newer.recorded_at - sample.recorded_at
        ).total_seconds() > max_sample_gap_seconds:
            break
        start = sample.recorded_at
        newer = sample
    return max(0.0, (end - start).total_seconds())


def _linear_interpolated_peaks(
    ecg_samples: Sequence[tuple[datetime, float]],
) -> list[datetime]:
    """Find simple local maxima; sufficient for prototype ECG feature extraction."""
    if len(ecg_samples) < 3:
        return []
    values = [value for _, value in ecg_samples]
    baseline = statistics.fmean(values)
    spread = statistics.pstdev(values)
    threshold = baseline + max(spread * 0.5, 1e-9)
    peaks: list[datetime] = []
    minimum_peak_gap = timedelta(milliseconds=250)
    for index in range(1, len(values) - 1):
        if (
            values[index] > threshold
            and values[index] >= values[index - 1]
            and values[index] > values[index + 1]
            and (
                not peaks
                or ecg_samples[index][0] - peaks[-1] >= minimum_peak_gap
            )
        ):
            peaks.append(ecg_samples[index][0])
    return peaks


def _ecg_features(
    ecg_samples: Sequence[tuple[datetime, float]],
) -> dict[str, float]:
    if not ecg_samples:
        return {
            "ecg_hr": math.nan,
            "rr_mean": math.nan,
            "rr_std": math.nan,
            "ecg_irregularity": math.nan,
            "ecg_signal_quality": 0.0,
        }
    values = [value for _, value in ecg_samples]
    spread = statistics.pstdev(values)
    peaks = _linear_interpolated_peaks(ecg_samples)
    rr_intervals = [
        (current - previous).total_seconds()
        for previous, current in zip(peaks, peaks[1:])
    ]
    rr_mean = statistics.fmean(rr_intervals) if rr_intervals else math.nan
    rr_std = statistics.pstdev(rr_intervals) if len(rr_intervals) > 1 else math.nan
    irregularity = (
        rr_std / rr_mean if rr_intervals and rr_mean else math.nan
    )
    signal_quality = min(1.0, len(peaks) / 3) if spread > 0 else 0.0
    return {
        "ecg_hr": 60 / rr_mean if rr_mean else math.nan,
        "rr_mean": rr_mean,
        "rr_std": rr_std,
        "ecg_irregularity": irregularity,
        "ecg_signal_quality": signal_quality,
    }


def _latest(samples: Sequence[VitalSample]) -> float:
    return samples[-1].value if samples else math.nan


def calculate_features(
    vitals: Mapping[str, Sequence[VitalSample]],
    ecg_samples: Sequence[tuple[datetime, float]],
    now: datetime,
    config: PipelineConfig = PipelineConfig(),
) -> dict[str, float]:
    """Calculate the requested feature vector for one patient."""
    heart_rate_samples = vitals.get("heart_rate_bpm", ())
    spo2_samples = vitals.get("spo2_percent", ())
    temperature_samples = vitals.get("temperature_c", ())
    cutoff_10s = now - WINDOW_10_SECONDS
    hr_10s = [
        sample
        for sample in heart_rate_samples
        if sample.recorded_at >= cutoff_10s
    ]
    spo2_10s = [
        sample
        for sample in spo2_samples
        if sample.recorded_at >= cutoff_10s
    ]
    temp_30s = temperature_samples
    all_spo2 = spo2_samples
    all_hr = heart_rate_samples
    ecg = _ecg_features(ecg_samples)
    latest_time = max(
        (
            *(
                sample.recorded_at
                for samples in vitals.values()
                for sample in samples
            ),
            *(recorded_at for recorded_at, _ in ecg_samples),
        ),
        default=now,
    )
    features = {
        "hr_current": _latest(hr_10s),
        "hr_mean_10s": _mean(hr_10s),
        "hr_slope_10s": _slope(hr_10s),
        "hr_abnormal_duration": _duration_above_or_below(
            all_hr,
            lambda value: value < config.heart_rate_low
            or value > config.heart_rate_high,
            config.max_sample_gap_seconds,
        ),
        "spo2_current": _latest(spo2_10s),
        "spo2_mean_10s": _mean(spo2_10s),
        "spo2_min_30s": min((sample.value for sample in all_spo2), default=math.nan),
        "spo2_slope_10s": _slope(spo2_10s),
        "spo2_low_duration": _duration_above_or_below(
            all_spo2,
            lambda value: value < config.spo2_low,
            config.max_sample_gap_seconds,
        ),
        "temp_current": _latest(temp_30s),
        "temp_mean_30s": _mean(temp_30s),
        "temp_slope_30s": _slope(temp_30s),
        **ecg,
        "num_abnormal_metrics": 0.0,
        "num_deteriorating_metrics": 0.0,
        "data_age": max(0.0, (now - latest_time).total_seconds()),
    }
    features["num_abnormal_metrics"] = float(
        sum(
            (
                not math.isnan(features["hr_current"])
                and (
                    features["hr_current"] < config.heart_rate_low
                    or features["hr_current"] > config.heart_rate_high
                ),
                not math.isnan(features["spo2_current"])
                and features["spo2_current"] < config.spo2_low,
                not math.isnan(features["temp_current"])
                and (
                    features["temp_current"] < config.temperature_low
                    or features["temp_current"] > config.temperature_high
                ),
                not math.isnan(features["ecg_irregularity"])
                and features["ecg_irregularity"] > config.ecg_irregularity_limit,
            )
        )
    )
    features["num_deteriorating_metrics"] = float(
        sum(
            (
                features["hr_slope_10s"] > config.deteriorating_slope,
                features["spo2_slope_10s"] < -config.deteriorating_slope,
                abs(features["temp_slope_30s"]) > config.deteriorating_slope / 10,
            )
        )
    )
    return features


def _json_safe_features(features: Mapping[str, float]) -> dict[str, float | None]:
    """Convert unavailable numeric features to JSON null."""
    return {
        name: None if math.isnan(value) else value
        for name, value in features.items()
    }


def _severity(value: float, low: float, high: float) -> float:
    if math.isnan(value):
        return 0.0
    if low <= value <= high:
        return 0.0
    distance = low - value if value < low else value - high
    return min(1.0, distance / max(high - low, 1e-9))


def calculate_scores(
    features: dict[str, float],
    config: PipelineConfig = PipelineConfig(),
) -> tuple[dict[str, float], float]:
    """Score vital categories separately and add an overall abnormality score."""
    heartbeat = statistics.fmean(
        (
            _severity(features["hr_current"], config.heart_rate_low, config.heart_rate_high),
            _severity(features["hr_mean_10s"], config.heart_rate_low, config.heart_rate_high),
            min(1.0, features["hr_abnormal_duration"] / config.abnormal_duration_seconds),
            min(1.0, max(0.0, features["hr_slope_10s"]) / config.deteriorating_slope),
        )
    )
    oxygen = statistics.fmean(
        (
            _severity(features["spo2_current"], config.spo2_low, 100),
            _severity(features["spo2_mean_10s"], config.spo2_low, 100),
            _severity(features["spo2_min_30s"], config.spo2_low, 100),
            min(1.0, max(0.0, -features["spo2_slope_10s"]) / config.deteriorating_slope),
            min(1.0, features["spo2_low_duration"] / config.abnormal_duration_seconds),
        )
    )
    temperature = statistics.fmean(
        (
            _severity(features["temp_current"], config.temperature_low, config.temperature_high),
            _severity(features["temp_mean_30s"], config.temperature_low, config.temperature_high),
            min(1.0, abs(features["temp_slope_30s"]) / (config.deteriorating_slope / 10)),
        )
    )
    ecg = statistics.fmean(
        (
            min(1.0, features["ecg_irregularity"] / config.ecg_irregularity_limit)
            if not math.isnan(features["ecg_irregularity"])
            else 0.0,
            (
                1.0 - features["ecg_signal_quality"]
                if not math.isnan(features["ecg_hr"])
                else 0.0
            ),
            _severity(features["ecg_hr"], config.heart_rate_low, config.heart_rate_high),
        )
    )
    categories = {
        "heartbeat": heartbeat,
        "oxygen": oxygen,
        "temperature": temperature,
        "ecg": ecg,
    }
    overall_abnormality = min(1.0, features["num_abnormal_metrics"] / 2)
    overall_deterioration = min(1.0, features["num_deteriorating_metrics"] / 2)
    overall = statistics.fmean((overall_abnormality, overall_deterioration))
    categories["overall_abnormality"] = overall
    vital_scores = [
        categories[name] for name in ("heartbeat", "oxygen", "temperature", "ecg")
    ]
    weighted_vital_score = statistics.fmean(vital_scores)
    patient_score = max(
        weighted_vital_score,
        max(vital_scores) * 0.8,
        overall,
    )
    return categories, patient_score


def _fetch_patient_ids(connection: Any) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT patient_id
            FROM public.health_readings
            WHERE recorded_at >= NOW() - INTERVAL '30 seconds'
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _fetch_inputs(
    connection: Any,
    patient_id: str,
    now: datetime,
) -> tuple[dict[str, list[VitalSample]], list[tuple[datetime, float]]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                recorded_at,
                heart_rate_bpm,
                spo2_percent,
                temperature_c,
                contact,
                heart_rate_valid,
                spo2_valid
            FROM public.health_readings
            WHERE patient_id = %s
              AND recorded_at >= %s
            ORDER BY recorded_at
            """,
            (patient_id, now - WINDOW_30_SECONDS),
        )
        rows = cursor.fetchall()
        has_contact = any(row["contact"] is True for row in rows)
        vitals = {
            name: [
                VitalSample(row["recorded_at"], row[column])
                for row in rows
                if has_contact
                and row[column] is not None
                and (
                    column != "heart_rate_bpm"
                    or row["heart_rate_valid"] is True
                )
                and (
                    column != "spo2_percent"
                    or row["spo2_valid"] is True
                )
            ]
            for name, column in (
                ("heart_rate_bpm", "heart_rate_bpm"),
                ("spo2_percent", "spo2_percent"),
                ("temperature_c", "temperature_c"),
            )
        }
        cursor.execute(
            """
            SELECT recorded_at, sample_value
            FROM public.ecg_samples
            WHERE patient_id = %s
              AND recorded_at >= %s
            ORDER BY recorded_at
            """,
            (patient_id, now - WINDOW_30_SECONDS),
        )
        ecg_rows = cursor.fetchall()
        ecg = (
            [(row["recorded_at"], row["sample_value"]) for row in ecg_rows]
            if has_contact
            else []
        )
    return vitals, ecg


def run_once(config: PipelineConfig = PipelineConfig()) -> None:
    """Compute and persist one snapshot for each patient with recent data."""
    now = datetime.now(timezone.utc)
    with connect() as connection:
        for patient_id in _fetch_patient_ids(connection):
            vitals, ecg = _fetch_inputs(connection, patient_id, now)
            features = calculate_features(vitals, ecg, now, config)
            categories, patient_score = calculate_scores(features, config)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.patient_feature_snapshots (
                        calculated_at, patient_id, features, category_scores, patient_score
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        now,
                        patient_id,
                        Jsonb(_json_safe_features(features)),
                        Jsonb(categories),
                        patient_score,
                    ),
                )
                print("insertded snapshot for patient", patient_id, "at", now.isoformat())


def run_forever(config: PipelineConfig = PipelineConfig()) -> None:
    """Run the pipeline once every five seconds."""
    initialize_schema()
    while True:
        started = time.monotonic()
        run_once(config)
        time.sleep(max(0.0, RUN_INTERVAL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    run_forever()
