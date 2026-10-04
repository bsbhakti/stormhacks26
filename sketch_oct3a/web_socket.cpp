#include <WiFi.h>
#include "web_socket.h"

const char* ssid = "GL-SFT1200-4e5";
const char* password = "goodlife";

const char* backendHost = "192.168.8.234";
const int backendPort = 5000;

String deviceId = "ESP001";

WebSocketsClient webSocket;

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {

  switch (type) {

    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected");
      break;

    case WStype_CONNECTED:
      Serial.println("WebSocket connected");
      break;

    case WStype_TEXT: {
      String message = String((char*) payload);

      Serial.print("Received: ");
      Serial.println(message);

      break;
    }
  }
}

void socket_connect() {

  WiFi.begin(ssid, password);

  Serial.print("Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("Connected!");
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
  

}