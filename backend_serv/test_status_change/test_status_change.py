"""Exercise the iOS patient-assignment status flow against a running backend.

Prerequisites:
    1. Start backend_serv/server.py.
    2. Have at least one patient with a recent feature snapshot and no active
       assignment (status 1, 2, or 3).

Run from the repository root:

    python backend_serv/test_status_change/test_status_change.py
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(
    base_url: str,
    path: str,
    method: str = "POST",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            return response.status, json.loads(response_body)
    except HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(response_body)
        except json.JSONDecodeError:
            details = {"error": response_body}
        raise RuntimeError(
            f"{method} {path} failed with HTTP {error.code}: {details}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Could not connect to {base_url}: {error.reason}") from error


def expect_status(response: dict[str, Any], expected: int, step: str) -> None:
    actual = response.get("status")
    if actual != expected:
        raise AssertionError(
            f"{step}: expected status {expected}, received {actual}: {response}"
        )
    print(f"[PASS] {step}: status={actual}, patient={response.get('patient_id')}")


def run_flow(base_url: str) -> None:
    _, assignment = request_json(base_url, "/assignments/next")
    assignment_id = assignment.get("id")
    if not isinstance(assignment_id, str) or not assignment_id:
        raise AssertionError(f"/assignments/next returned no assignment ID: {assignment}")
    expect_status(assignment, 1, "next assignment")

    _, found = request_json(base_url, f"/assignments/{assignment_id}/found")
    expect_status(found, 2, "mark patient found")

    _, continued = request_json(
        base_url,
        f"/assignments/{assignment_id}/complete",
        body={"continue_monitoring": True},
    )
    expect_status(continued, 2, "continue monitoring")

    _, completed = request_json(
        base_url,
        f"/assignments/{assignment_id}/complete",
        body={"continue_monitoring": False},
    )
    expect_status(completed, 3, "stop monitoring")

    print(f"[PASS] complete status flow for assignment={assignment_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5000",
        help="backend URL (default: %(default)s)",
    )
    args = parser.parse_args()

    try:
        run_flow(args.base_url)
    except (AssertionError, RuntimeError) as error:
        raise SystemExit(f"[FAIL] {error}") from error


if __name__ == "__main__":
    main()
