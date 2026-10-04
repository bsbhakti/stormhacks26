#include <Wire.h>
#include <Arduino.h>

void check_connected_dev(){
  for (byte address = 1; address < 127; address++) {
        Wire.beginTransmission(address);

        if (Wire.endTransmission() == 0) {
            Serial.print("Found device at 0x");
            Serial.println(address, HEX);
        }
    }
}

float get_body_temp(){
  Wire.beginTransmission(0x48);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0){
    Serial.println("Transmission failed to end");
    return 0.0;
  }
  int bytes = Wire.requestFrom(0x48, 2);
  if (bytes != 2) {
        Serial.print("Expected 2 bytes, got ");
        Serial.println(bytes);
        return NAN;
    }

  uint8_t msb = Wire.read();
  uint8_t lsb = Wire.read();
  int16_t raw = (msb << 8) | lsb;
  raw &= 0x3FFF;

    Serial.print("MSB: 0x");
    Serial.println(msb, HEX);

    Serial.print("LSB: 0x");
    Serial.println(lsb, HEX);

    Serial.print("Raw: ");
    Serial.println(raw);
  float temp = raw * 0.00390625;
  return temp;

}