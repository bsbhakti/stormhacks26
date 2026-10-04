from flask import Flask, jsonify, request

from backend.timescale_db import initialize_schema, reading_from_payload, write_reading

app = Flask(__name__)

@app.post("/sensor-data")
def sensor_data():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="request body must be a JSON object"), 400

    try:
        reading = reading_from_payload(data)
        write_reading(reading)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception:
        app.logger.exception("Unable to write sensor reading to TimescaleDB")
        return jsonify(error="sensor reading could not be stored"), 503

    return jsonify(status="stored"), 201


if __name__ == "__main__":
    initialize_schema()
    app.run(host="0.0.0.0", port=5000)