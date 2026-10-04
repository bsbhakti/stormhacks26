#!/usr/bin/env python3
"""Standalone ESP mimic service for demoing the triage queue.

Runs separately from the Flask server. Five virtual wearables POST the same
JSON shape as a real ESP to /sensor-data so the backend can store them in
TimescaleDB and the web UI can rank them.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ECG_SAMPLES = 80
SAMPLE_RATE_HZ = 250


@dataclass(frozen=True)
class DeviceProfile:
    device_id: str
    patient_id: str
    label: str
    heart_rate: float
    heart_rate_wander: float
    spo2: float
    spo2_wander: float
    temperature: float
    temperature_wander: float
    trend_hr: float = 0.0
    trend_spo2: float = 0.0
    drop_contact_every: float = 0.0


PROFILES = (
    DeviceProfile(
        device_id="ESP-ALPHA",
        patient_id="patient_sim_alpha",
        label="shock / hypoxia",
        heart_rate=148,
        heart_rate_wander=6,
        spo2=87,
        spo2_wander=1.6,
        temperature=38.6,
        temperature_wander=0.15,
    ),
    DeviceProfile(
        device_id="ESP-BRAVO",
        patient_id="patient_sim_bravo",
        label="deteriorating",
        heart_rate=118,
        heart_rate_wander=4,
        spo2=93,
        spo2_wander=0.8,
        temperature=37.9,
        temperature_wander=0.1,
        trend_hr=0.08,
        trend_spo2=-0.015,
    ),
    DeviceProfile(
        device_id="ESP-CHARLIE",
        patient_id="patient_sim_charlie",
        label="stable",
        heart_rate=74,
        heart_rate_wander=3,
        spo2=98,
        spo2_wander=0.4,
        temperature=36.7,
        temperature_wander=0.08,
    ),
    DeviceProfile(
        device_id="ESP-DELTA",
        patient_id="patient_sim_delta",
        label="bradycardia",
        heart_rate=46,
        heart_rate_wander=2,
        spo2=94,
        spo2_wander=0.7,
        temperature=35.1,
        temperature_wander=0.1,
    ),
    DeviceProfile(
        device_id="ESP-ECHO",
        patient_id="patient_sim_echo",
        label="intermittent contact",
        heart_rate=102,
        heart_rate_wander=4,
        spo2=95,
        spo2_wander=0.6,
        temperature=37.2,
        temperature_wander=0.08,
        drop_contact_every=22,
    ),
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _wave(now: float, phase: float, wander: float) -> float:
    return wander * math.sin(now / 7.0 + phase) + random.uniform(-wander * 0.25, wander * 0.25)


def synthetic_ecg(heart_rate: float, irregular: bool = False) -> list[float]:
    """Build a short QRS-like strip so the dashboard ECG is not a flat line."""
    rr = 60.0 / max(heart_rate, 30.0)
    samples: list[float] = []
    jitter = 0.08 if irregular else 0.0
    for index in range(ECG_SAMPLES):
        instant = index / SAMPLE_RATE_HZ
        cycle = (instant % (rr * (1.0 + random.uniform(-jitter, jitter)))) / rr
        if 0.17 < cycle < 0.24:
            value = 1.7 * math.sin((cycle - 0.17) / 0.07 * math.pi)
        elif 0.28 < cycle < 0.42:
            value = -0.22 * math.sin((cycle - 0.28) / 0.14 * math.pi)
        else:
            value = 0.06 * math.sin(cycle * 2 * math.pi)
        samples.append(round(value + random.uniform(-0.03, 0.03), 3))
    return samples


def reading_for(profile: DeviceProfile, elapsed: float) -> dict[str, Any]:
    phase = sum(ord(char) for char in profile.device_id) / 17.0
    heart_rate = _clamp(
        profile.heart_rate + profile.trend_hr * elapsed + _wave(elapsed, phase, profile.heart_rate_wander),
        35,
        190,
    )
    spo2 = _clamp(
        profile.spo2 + profile.trend_spo2 * elapsed + _wave(elapsed, phase + 1.2, profile.spo2_wander),
        70,
        100,
    )
    temperature = _clamp(
        profile.temperature + _wave(elapsed, phase + 2.1, profile.temperature_wander),
        33.5,
        41.0,
    )

    contact = True
    if profile.drop_contact_every and (elapsed % profile.drop_contact_every) < 4:
        contact = False

    heart_rate_valid = contact
    spo2_valid = contact
    return {
        "patient_id": profile.patient_id,
        "device_id": profile.device_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "heart_rate_bpm": -1 if not heart_rate_valid else round(heart_rate),
        "spo2_percent": -1 if not spo2_valid else round(spo2),
        "temperature_c": round(temperature, 2),
        "contact": int(contact),
        "hr_valid": int(heart_rate_valid),
        "spo2_valid": int(spo2_valid),
        "ecg_count": ECG_SAMPLES if contact else 0,
        "ecg": synthetic_ecg(heart_rate, irregular=profile.device_id == "ESP-ALPHA") if contact else [],
        "metadata": {
            "source": "esp_sim",
            "label": profile.label,
        },
    }


def send_reading(endpoint: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=8) as response:
        if response.status >= 300:
            raise RuntimeError(f"{payload['device_id']} -> {response.status}")


def log_reading(payload: dict[str, Any]) -> None:
    contact = "on" if payload["contact"] else "off"
    print(
        f"{payload['device_id']:<11} "
        f"hr={payload['heart_rate_bpm']:>3}  "
        f"spo2={payload['spo2_percent']:>3}  "
        f"temp={payload['temperature_c']:>5}  "
        f"contact={contact}",
        flush=True,
    )


def run(endpoint: str, interval: float) -> None:
    print(f"Mimicking {len(PROFILES)} ESPs -> {endpoint} every {interval:.1f}s")
    for profile in PROFILES:
        print(f"  {profile.device_id}  {profile.patient_id}  ({profile.label})")
    print("Ctrl+C to stop.\n", flush=True)

    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        for index, profile in enumerate(PROFILES):
            payload = reading_for(profile, elapsed)
            try:
                send_reading(endpoint, payload)
                log_reading(payload)
            except HTTPError as error:
                details = error.read().decode("utf-8", errors="replace")
                print(f"{profile.device_id} rejected {error.code}: {details}", flush=True)
            except URLError as error:
                print(f"server unreachable ({error.reason}); retrying…", flush=True)
                time.sleep(2)
                break
            except Exception as error:
                print(f"{profile.device_id} failed: {error!r}", flush=True)
            time.sleep(interval / len(PROFILES))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:5000/sensor-data",
        help="Flask sensor-data URL (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between a full 5-device round (default: %(default)s)",
    )
    args = parser.parse_args()
    try:
        run(args.endpoint, max(0.25, args.interval))
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()
