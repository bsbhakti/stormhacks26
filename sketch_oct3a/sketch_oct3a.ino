#include <WiFi.h>
#include <HTTPClient.h>
#include "body_temp.h"
#include "Wire.h"
#include "ble.h"
#include "web_socket.h"

// const char* ssid = "GL-SFT1200-4e5";
// const char* password = "goodlife";
HTTPClient http;


void setup() {
    Serial.begin(115200);

    // WiFi.begin(ssid, password);
    // Wire.begin(21, 22);

    // Serial.print("Connecting");

    // while (WiFi.status() != WL_CONNECTED) {
    //     delay(500);
    //     Serial.print(".");
    // }

    // Serial.println();
    // Serial.println("Connected!");
    // Serial.print("ESP32 IP: ");
    // Serial.println(WiFi.localIP());

    // http.begin("http://192.168.8.234:5000/sensor-data");

    adv_ble();
    socket_connect();
}

void loop() {
    socket_loop();

  // Serial.println("Scanning...");
    // check_connected_dev();
    // delay(2000);

    // Serial.print("Getting temp:");
    // Serial.println(get_body_temp());

    // http.addHeader("Content-Type", "application/json");

    // String data = "{\"patient_id\":\"P001\",\"heart_rate\":78}";

    // int response = http.POST(data);

    // Serial.println(response);

    // http.end();
}