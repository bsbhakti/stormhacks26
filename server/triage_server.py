#!/usr/bin/env python3
"""Minimal triage assignment server for Rapid Triage.

POST /assignments/next
    -> {"id": "...", "name": "TAG-ALPHA"}

POST /assignments/<id>/complete
    body: {"status": "helped"}
    -> {"ok": true}

POST /tags
    body: {"name": "your-ble-advertised-name"}
    queues a tag for the next Find Patient request.
"""

from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = 8080

queue = ["TAG-ALPHA", "TAG-BRAVO", "TAG-CHARLIE"]
assignments: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        print(f"[triage] {self.address_string()} {format % args}")

    def _send(self, code: int, body: dict | None = None) -> None:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._send(204)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/assignments/next":
            self._next_assignment()
            return
        self._send(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/assignments/next":
            self._next_assignment()
            return
        if path == "/tags":
            self._add_tag()
            return
        if path.startswith("/assignments/") and path.endswith("/complete"):
            assignment_id = path.removeprefix("/assignments/").removesuffix("/complete")
            self._complete(assignment_id)
            return
        self._send(404, {"error": "Not found"})

    def _next_assignment(self) -> None:
        if not queue:
            self._send(404, {"error": "No patients waiting."})
            return
        name = queue.pop(0)
        assignment_id = str(uuid.uuid4())
        assignments[assignment_id] = {"id": assignment_id, "name": name, "status": "assigned"}
        print(f"[triage] assigned {assignment_id} -> {name}")
        self._send(200, {"id": assignment_id, "name": name})

    def _add_tag(self) -> None:
        body = self._read_json()
        name = str(body.get("name", "")).strip()
        if not name:
            self._send(400, {"error": "Missing name"})
            return
        queue.append(name)
        print(f"[triage] queued {name}. waiting={queue}")
        self._send(200, {"ok": True, "queued": name, "waiting": queue})

    def _complete(self, assignment_id: str) -> None:
        assignment = assignments.get(assignment_id)
        if assignment is None:
            self._send(404, {"error": "Unknown assignment"})
            return
        body = self._read_json()
        status = str(body.get("status", "helped")).strip() or "helped"
        assignment["status"] = status
        print(f"[triage] completed {assignment_id} ({assignment['name']}) status={status}")
        self._send(200, {"ok": True, "id": assignment_id, "status": status})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Triage server listening on http://0.0.0.0:{PORT}")
    print(f"Queued tags: {queue}")
    print("POST /tags {\"name\":\"your-advertised-name\"} to add a real BLE tag.")
    server.serve_forever()
