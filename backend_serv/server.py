import logging
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request
from flask_sock import Sock

from timescale_db import initialize_schema

app = Flask(__name__)
sock = Sock(app)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

connected_devices: dict[str, Any] = {}
connected_devices_lock = Lock()

@app.post("/sensor-data")
def sensor_data():
    data = request.get_json(silent=True)
    # print("Received sensor data:", data)
    if not isinstance(data, dict):
        return jsonify(error="request body must be a JSON object"), 400


    # try:
    #     print("Received sensor data:", data)
    #     reading = reading_from_payload(data)
    #     write_reading(reading)
    # except ValueError as error:
    #     return jsonify(error=str(error)), 400
    # except Exception:
    #     app.logger.exception("Unable to write sensor reading to TimescaleDB")
    #     return jsonify(error="sensor reading could not be stored"), 503

    return jsonify(status="stored"), 201


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
    logger.info("WebSocket message sent to device=%s: %r", device_id, message)
    return True


@app.post("/devices/<device_id>/send")
def send_to_device_http(device_id: str):
    """Small test/control endpoint for sending a message to an ESP32."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        return jsonify(error="request body must contain a string message"), 400

    if not send_to_device(device_id, data["message"]):
        return jsonify(error="device is not connected"), 404
    return jsonify(status="sent", device_id=device_id), 200


if __name__ == "__main__":
    # initialize_schema()
    app.run(host="0.0.0.0", port=5000)