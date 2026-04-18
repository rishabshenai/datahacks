// sentinel_firmware.ino — Aegis Ocean
// Arduino Modulino (Thermo + Distance + Movement) via Qwiic daisy-chain
//
// Library: "Arduino_Modulino" — install from Arduino Library Manager
// Board:   Arduino Uno
// Baud:    9600
//
// Acceptance test:
//   Serial Monitor → valid JSON every 2 seconds
//   Warm Thermo in hand → temp rises
//   Add water under Distance module → dist_mm increases
//   Shake Movement → turbulence jumps

#include <Modulino.h>

ModulinoThermo   thermo;
ModulinoDistance distance;
ModulinoMovement movement;

void setup() {
  Serial.begin(9600);
  Modulino.begin();
  thermo.begin();
  distance.begin();
  movement.begin();
}

void loop() {
  float tempC   = thermo.getTemperature();
  float dist_mm = distance.get();
  float ax = movement.getAccelerationX();
  float ay = movement.getAccelerationY();
  float az = movement.getAccelerationZ();

  // Subtract gravity (9.81 m/s²) to isolate wave-like motion
  float turbulence = sqrt(ax*ax + ay*ay + az*az) - 9.81;
  if (turbulence < 0) turbulence = 0;

  Serial.print("{\"temp\":");
  Serial.print(tempC, 2);
  Serial.print(",\"distance_mm\":");
  Serial.print(dist_mm, 1);
  Serial.print(",\"accel_x\":");
  Serial.print(ax, 3);
  Serial.print(",\"accel_y\":");
  Serial.print(ay, 3);
  Serial.print(",\"accel_z\":");
  Serial.print(az, 3);
  Serial.print(",\"turbulence\":");
  Serial.print(turbulence, 3);
  Serial.print(",\"ts\":");
  Serial.print(millis());
  Serial.println("}");

  delay(2000);
}
