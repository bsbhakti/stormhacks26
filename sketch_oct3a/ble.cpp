#include "ble.h"

void adv_ble(){
  BLEDevice::init("patient_001"); 
  BLEAdvertising *advertising =
  BLEDevice::getAdvertising();

  advertising->start();
  Serial.println("BLE ad started");
}