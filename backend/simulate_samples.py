"""Send five simulated wearable readings to the Flask receiver."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SampleMetadata(TypedDict):
    source: str
    sample_number: int


class Sample(TypedDict):
    patient_id: str
    device_id: str
    recorded_at: str
    heart_rate_bpm: int
    spo2_percent: int
    temperature_c: float
    ecg: list[float]
    metadata: SampleMetadata


def simulated_samples() -> list[Sample]:
    """Return five deterministic readings for one simulated patient."""
    start = datetime.now(timezone.utc).replace(microsecond=0)
    measurements = [
        (82, 98, 36.7, [0.12, 0.15, 0.11]),
        (86, 97, 36.8, [0.14, 0.18, 0.13]),
        (91, 96, 36.9, [0.19, 0.21, 0.17]),
        (98, 95, 37.1, [0.24, 0.29, 0.22]),
        (103, 94, 37.2, [0.31, 0.35, 0.28]),
    ]

    return [
        {
            "patient_id": "simulated-patient-001",
            "device_id": "simulated-watch-001",
            "recorded_at": (start + timedelta(seconds=index)).isoformat(),
            "heart_rate_bpm": heart_rate,
            "spo2_percent": spo2,
            "temperature_c": temperature,
            "ecg": ecg,
            "metadata": {
                "source": "simulation",
                "sample_number": index + 1,
            },
        }
        for index, (heart_rate, spo2, temperature, ecg) in enumerate(measurements)
    ]


def send_sample(endpoint: str, sample: Sample) -> None:
    """Send one sample and raise an actionable error for non-success responses."""
    body = json.dumps(sample).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            print(f"{sample['metadata']['sample_number']}/5: {response.status} {response_body}")
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"server rejected sample {sample['metadata']['sample_number']}: "
            f"{error.code} {details}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"could not reach {endpoint}: {error.reason}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:5000/sensor-data",
        help="sensor-data endpoint (default: %(default)s)",
    )
    args = parser.parse_args()

    for sample in simulated_samples():
        send_sample(args.endpoint, sample)


if __name__ == "__main__":
    main()
