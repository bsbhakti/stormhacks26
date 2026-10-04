# StormHacks health wearable

## ESP32 WebSocket test

The backend accepts WebSocket connections at
`/ws/device/<device_id>`. The example sketch
[`backend_serv/esp32_socket_counter.ino`](./backend_serv/esp32_socket_counter.ino)
connects to the server and sends the text messages `1`, `2`, `3`, and so on,
once per second. Install the Arduino `WebSockets` library before compiling.

Start the backend from `backend_serv/`:

```bash
cd backend_serv
python server.py
```

Set `backendHost` in the sketch to the Mac's LAN IP address. The ESP32 and Mac
must be connected to the same router.