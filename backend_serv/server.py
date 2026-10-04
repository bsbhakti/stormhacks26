import logging
from threading import Lock
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from flask import Flask, jsonify, request
from flask_sock import Sock

from timescale_db import connect, initialize_schema, reading_from_payload, write_reading

app = Flask(__name__)
sock = Sock(app)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

connected_devices: dict[str, Any] = {}
connected_devices_lock = Lock()

STATUS_YET_TO_BE_HELPED = 0
STATUS_FINDING = 1
STATUS_FOUND = 2
STATUS_OUT_OF_QUEUE = 3

ASSIGNMENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.patient_assignments (
    assignment_id UUID PRIMARY KEY,
    patient_id TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    esp_device_id TEXT,
    status SMALLINT NOT NULL CHECK (status BETWEEN 0 AND 3),
    assigned_at TIMESTAMPTZ NOT NULL,
    status_updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    continue_monitoring BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS patient_assignments_status_idx
    ON public.patient_assignments (status, assigned_at);

CREATE TABLE IF NOT EXISTS public.patient_status_history (
    event_id BIGSERIAL PRIMARY KEY,
    assignment_id UUID NOT NULL REFERENCES public.patient_assignments(assignment_id),
    patient_id TEXT NOT NULL,
    status SMALLINT NOT NULL CHECK (status BETWEEN 0 AND 3),
    changed_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL
);
"""


def initialize_assignment_schema() -> None:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(ASSIGNMENT_SCHEMA_SQL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _send_patient_stage(
    device_id: str | None,
    stage: int,
) -> None:
    if device_id is not None:
        message = str(stage)
        delivered = send_to_device(device_id, message)
        logger.info(
            "Patient stage sent to ESP: device_id=%s stage=%s delivered=%s",
            device_id,
            message,
            delivered,
        )


def _record_status(
    assignment_id: str,
    status: int,
    source: str,
    continue_monitoring: bool = False,
) -> dict[str, Any] | None:
    changed_at = _now()
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.patient_assignments
                SET status = %s,
                    status_updated_at = %s,
                    completed_at = CASE
                        WHEN %s = 0 THEN NULL
                        WHEN %s = 3 THEN %s
                        ELSE completed_at
                    END,
                    continue_monitoring = %s
                WHERE assignment_id = %s
                RETURNING assignment_id, patient_id, tag_name, esp_device_id, status
                """,
                (
                    status,
                    changed_at,
                    status,
                    status,
                    changed_at,
                    continue_monitoring,
                    assignment_id,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                INSERT INTO public.patient_status_history
                    (assignment_id, patient_id, status, changed_at, source)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (assignment_id, row[1], status, changed_at, source),
            )
    result = {
        "id": str(row[0]),
        "patient_id": row[1],
        "name": row[2],
        "device_id": row[3],
        "status": row[4],
    }
    _send_patient_stage(result["device_id"], status)
    return result


@app.post("/sensor-data")
def sensor_data():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="request body must be a JSON object"), 400

    try:
        # print("Received sensor data:", data)
        reading = reading_from_payload(data)
        write_reading(reading)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        app.logger.exception("Unable to write sensor reading to TimescaleDB")
        return jsonify(error="sensor reading could not be stored"), 503

    return jsonify(status="stored"), 201


@app.post("/assignments/next")
def next_assignment():
    changed_at = _now()
    with connect() as connection:
        with connection.cursor() as cursor:
            # Serialize assignment selection so concurrent iOS requests cannot
            # choose the same highest-priority patient.
            cursor.execute("SELECT pg_advisory_xact_lock(921337)")
            cursor.execute(
                """
                WITH latest_scores AS (
                    SELECT DISTINCT ON (patient_id)
                        patient_id,
                        patient_score,
                        calculated_at
                    FROM public.patient_feature_snapshots
                    ORDER BY patient_id, calculated_at DESC
                ),
                latest_devices AS (
                    SELECT DISTINCT ON (patient_id)
                        patient_id,
                        device_id
                    FROM public.health_readings
                    ORDER BY patient_id, recorded_at DESC
                )
                SELECT
                    scores.patient_id,
                    devices.device_id,
                    scores.patient_score,
                    scores.calculated_at
                FROM latest_scores AS scores
                LEFT JOIN latest_devices AS devices
                    ON devices.patient_id = scores.patient_id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM public.patient_assignments AS assignments
                    WHERE assignments.patient_id = scores.patient_id
                      AND assignments.status IN (1, 2, 3)
                )
                ORDER BY scores.patient_score DESC, scores.calculated_at ASC
                LIMIT 1
                """,
            )
            row = cursor.fetchone()
            if row is None:
                return jsonify(error="No yet-to-be-helped patients are available."), 404

            patient_id, device_id, patient_score, _ = row
            assignment_id = uuid4()
            cursor.execute(
                """
                INSERT INTO public.patient_assignments (
                    assignment_id,
                    patient_id,
                    tag_name,
                    esp_device_id,
                    status,
                    assigned_at,
                    status_updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    assignment_id,
                    patient_id,
                    patient_id,
                    device_id,
                    STATUS_YET_TO_BE_HELPED,
                    changed_at,
                    changed_at,
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.patient_status_history
                    (assignment_id, patient_id, status, changed_at, source)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    assignment_id,
                    patient_id,
                    STATUS_YET_TO_BE_HELPED,
                    changed_at,
                    "score_queue",
                ),
            )
            cursor.execute(
                """
                UPDATE public.patient_assignments
                SET status = %s, status_updated_at = %s
                WHERE assignment_id = %s
                """,
                (STATUS_FINDING, changed_at, assignment_id),
            )
            cursor.execute(
                """
                INSERT INTO public.patient_status_history
                    (assignment_id, patient_id, status, changed_at, source)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    assignment_id,
                    patient_id,
                    STATUS_FINDING,
                    changed_at,
                    "ios_assignment",
                ),
            )
    result = {
        "id": str(assignment_id),
        "patient_id": patient_id,
        "name": patient_id,
        "device_id": device_id,
        "status": STATUS_FINDING,
        "patient_score": patient_score,
    }
    _send_patient_stage(result["device_id"], STATUS_FINDING)
    return jsonify(result), 200


@app.post("/assignments/<assignment_id>/found")
def assignment_found(assignment_id: str):
    result = _record_status(assignment_id, STATUS_FOUND, "ios_found")
    if result is None:
        return jsonify(error="Unknown assignment"), 404
    return jsonify(result), 200


@app.post("/assignments/<assignment_id>/status")
def assignment_status(assignment_id: str):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {
        STATUS_YET_TO_BE_HELPED,
        STATUS_FINDING,
        STATUS_FOUND,
        STATUS_OUT_OF_QUEUE,
    }:
        return jsonify(error="status must be 0, 1, 2, or 3"), 400

    result = _record_status(
        assignment_id,
        status,
        "ios_status",
        continue_monitoring=status == STATUS_YET_TO_BE_HELPED,
    )
    if result is None:
        return jsonify(error="Unknown assignment"), 404
    return jsonify(result), 200


@app.post("/assignments/<assignment_id>/complete")
def complete_assignment(assignment_id: str):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    requeue = data.get("requeue", False)
    continue_monitoring = data.get(
        "continue_monitoring",
        data.get("continueMonitoring", False),
    )
    if status is None:
        if not isinstance(requeue, bool) or not isinstance(continue_monitoring, bool):
            return jsonify(error="requeue and continue_monitoring must be booleans"), 400
        status = (
            STATUS_YET_TO_BE_HELPED
            if requeue or continue_monitoring
            else STATUS_OUT_OF_QUEUE
        )
    if status not in {STATUS_YET_TO_BE_HELPED, STATUS_OUT_OF_QUEUE}:
        return jsonify(error="complete status must be 0 or 3"), 400

    result = _record_status(
        assignment_id,
        status,
        "ios_complete",
        continue_monitoring=status == STATUS_YET_TO_BE_HELPED,
    )
    if result is None:
        return jsonify(error="Unknown assignment"), 404
    return jsonify(result), 200


@sock.route("/ws/device/<device_id>")
def device_socket(ws, device_id: str):
    """Register an ESP32 socket and keep it open until the client disconnects."""
    logger.info("WebSocket connected: device_id=%s", device_id)
    with connected_devices_lock:
        previous_socket = connected_devices.get(device_id)
        connected_devices[device_id] = ws

    if previous_socket is not None:
        logger.warning("Replacing existing WebSocket: device_id=%s", device_id)

    try:
        while True:
            message = ws.receive()
            if message is None:
                logger.info("WebSocket receive returned None: device_id=%s", device_id)
                break

            logger.info("WebSocket message from device=%s: %r", device_id, message)
    finally:
        with connected_devices_lock:
            if connected_devices.get(device_id) is ws:
                del connected_devices[device_id]
        logger.info("WebSocket disconnected: device_id=%s", device_id)


def send_to_device(device_id: str, message: str) -> bool:
    """Send a text message to a connected device.

    Returns False when the device is not currently connected. The caller can
    use the return value to mark a command as undelivered.
    """
    with connected_devices_lock:
        websocket = connected_devices.get(device_id)
        if websocket is None:
            return False
        try:
            websocket.send(message)
        except Exception:
            logger.exception("Unable to send to device=%s", device_id)
            return False
    print("WebSocket message sent to device=%s: %r", device_id, message)
    return True


@app.post("/devices/<device_id>/send")
def send_to_device_http(device_id: str):
    """Send a bare patient stage integer to an ESP32."""
    data = request.get_json(silent=True)
    stage = data.get("stage") if isinstance(data, dict) else None
    if (
        not isinstance(stage, str)
        or stage not in {"0", "1", "2", "3"}
    ):
        return jsonify(error="stage must be an integer from 0 to 3"), 400

    if not send_to_device(device_id, stage):
        return jsonify(error="device is not connected"), 404
    return jsonify(status="sent", device_id=device_id, stage=stage), 200


if __name__ == "__main__":
    initialize_schema()
    initialize_assignment_schema()
    app.run(host="0.0.0.0", port=5000)