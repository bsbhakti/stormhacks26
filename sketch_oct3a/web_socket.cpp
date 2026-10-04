#include <WiFi.h>
#include "web_socket.h"

const char* ssid = "GL-SFT1200-4e5";
const char* password = "goodlife";

const char* backendHost = "192.168.8.234";
const int backendPort = 5000;

String deviceId = "ESP001";

WebSocketsClient webSocket;
unsigned long lastStatusAt = 0;

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {

  switch (type) {

    case WStype_DISCONNECTED:
      Serial.println("[WS] disconnected");
      break;

    case WStype_CONNECTED:
      Serial.print("[WS] connected to ws://");
      Serial.print(backendHost);
      Serial.print(":");
      Serial.print(backendPort);
      Serial.print("/ws/device/");
      Serial.println(deviceId);
      break;

    case WStype_TEXT: {
      Serial.print("[WS] received: ");
      Serial.write(payload, length);
      Serial.println();

      break;
    }

    case WStype_ERROR:
      Serial.println("[WS] error");
      break;

    case WStype_PING:
      Serial.println("[WS] ping");
      break;

    case WStype_PONG:
      Serial.println("[WS] pong");
      break;

    default:
      break;
  }
}

void socket_connect() {

  Serial.print("[WS] WiFi status before connect: ");
  Serial.println(WiFi.status());
  WiFi.begin(ssid, password);

  Serial.print("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("\n[WiFi] connected");
  Serial.print("ESP IP: ");
  Serial.println(WiFi.localIP());

  String path = "/ws/device/" + deviceId;

  webSocket.begin(
    backendHost,
    backendPort,
    path.c_str()
  );

  webSocket.onEvent(webSocketEvent);

  // reconnect every 5 seconds if connection drops
  webSocket.setReconnectInterval(5000);
  webSocket.enableHeartbeat(15000, 3000, 2);
  Serial.println("[WS] connection attempt started");
}

void socket_loop() {
  webSocket.loop();

  if (millis() - lastStatusAt >= 5000) {
    lastStatusAt = millis();
    Serial.print("[WS] status: ");
    Serial.print(webSocket.isConnected() ? "connected" : "not connected");
    Serial.print(", WiFi: ");
    Serial.println(WiFi.status() == WL_CONNECTED ? "connected" : "not connected");
  }
}