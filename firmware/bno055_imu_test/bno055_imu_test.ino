// =============================================================================
// bno055_imu_test.ino
// BNO055 IMU — Euler angle visualiser for the Arduino IDE Serial Plotter
// Hardware: ESP32 Dev Board (USB power, 3.3 V native — no level shifter needed)
//           BNO055 wired directly: SDA → GPIO 21, SCL → GPIO 22
//           VCC → 3.3 V, GND → GND. No motors or external batteries required.
//
// HOW TO USE THE SERIAL PLOTTER:
//   1. In Arduino IDE 2.x: select your ESP32 board under Tools → Board.
//   2. Upload this sketch to your ESP32 via USB.
//   3. Open Tools → Serial Plotter  (or press Ctrl+Shift+L).
//   4. Set the baud rate drop-down in the plotter to 115200.
//   5. Three labelled traces appear: Yaw (heading), Pitch, Roll.
//   6. Tilt your breadboard in any direction — watch the traces move live.
//
// AXIS DEFINITIONS (BNO055 Euler output):
//   Yaw   (euler.x) — rotation around Z (compass heading), 0–360°
//   Pitch (euler.y) — nose up / down,  ±90°
//   Roll  (euler.z) — tilt left / right, ±180°
//
// REQUIRED LIBRARIES (install via Sketch → Include Library → Manage Libraries):
//   • Adafruit BNO055          (by Adafruit)
//   • Adafruit Unified Sensor  (dependency — installed automatically with above)
// =============================================================================

// =============================================================================
// SECTION 1 — INCLUDES & OBJECT CREATION
// =============================================================================

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>

// ESP32 I2C pin assignment — GPIO 21 = SDA, GPIO 22 = SCL (hardware I2C defaults).
// Wire.begin() in setup() passes these explicitly for clarity.
const int PIN_SDA = 21;
const int PIN_SCL = 22;

// BNO055 sensor object — ID 55, default I2C address 0x28
// If you have pulled the ADR pin HIGH on your breakout, change to 0x29.
Adafruit_BNO055 bno = Adafruit_BNO055(55, 0x29);

// =============================================================================
// SECTION 2 — TUNABLE PARAMETERS
// =============================================================================

const uint16_t SAMPLE_INTERVAL_MS = 50;   // Loop delay in ms → ~20 Hz update rate
                                           // Decrease for faster plotter updates,
                                           // increase if the plotter feels choppy.

// =============================================================================
// SECTION 3 — setup()
// =============================================================================

void setup() {
    Serial.begin(115200);
    // Small delay lets the Serial Plotter connect before the first data line arrives.
    delay(500);

    // Explicitly initialise I2C with the wired GPIO pins before starting the sensor.
    Wire.begin(PIN_SDA, PIN_SCL);

    if (!bno.begin()) {
        // Sensor not found — check direct wiring and I2C address.
        Serial.println("ERROR: BNO055 not detected. Check wiring & I2C address.");
        Serial.println("  SDA → GPIO 21, SCL → GPIO 22 (direct, no level shifter).");
        Serial.println("  VCC must be 3.3 V — do NOT connect to 5 V on the ESP32.");
        Serial.println("  If ADR pin is HIGH on your breakout, change address to 0x29.");
        while (true) { delay(1000); }   // Halt — nothing else to do without the sensor.
    }

    // Use the BNO055's onboard 32.768 kHz crystal for improved accuracy.
    // Safe to leave enabled; has no effect if the external crystal is absent.
    bno.setExtCrystalUse(true);

    Serial.println("BNO055 initialised. Opening Serial Plotter...");
    delay(200);
}

// =============================================================================
// SECTION 4 — loop()
//
// Reads Euler angles and prints them in the format that Arduino IDE 2.x
// Serial Plotter expects for labelled traces:
//
//   Yaw:90.50,Pitch:10.20,Roll:-5.30
//
// Each iteration outputs exactly one '\n'-terminated line.
// Labels are constant so the plotter keeps them assigned to the same traces.
// =============================================================================

void loop() {
    sensors_event_t event;
    bno.getEvent(&event);

    float yaw   = event.orientation.x;   // Heading, 0–360°
    float pitch = event.orientation.y;   // Nose up/down, ±90°
    float roll  = event.orientation.z;   // Tilt left/right, ±180°

    // Labelled CSV — Serial Plotter 2.x parses "Label:value" pairs.
    Serial.print("Yaw:");
    Serial.print(yaw, 2);
    Serial.print(",Pitch:");
    Serial.print(pitch, 2);
    Serial.print(",Roll:");
    Serial.println(roll, 2);   // println provides the required '\n'

    delay(SAMPLE_INTERVAL_MS);
}

// =============================================================================
// END OF FILE
//
// TROUBLESHOOTING:
//
//   Flat line at 0 in plotter
//     → Open Serial Monitor at 115200 — if "ERROR: BNO055 not detected" appears,
//       the sensor was not found on I2C. Re-check SDA → GPIO 21, SCL → GPIO 22
//       and confirm VCC is connected to the ESP32's 3.3 V pin (NOT 5 V).
//
//   Yaw drifts slowly even when still
//     → Normal on a table without magnetic calibration. Wave the sensor in a
//       figure-8 pattern to calibrate the magnetometer.
//
//   Pitch / Roll values seem swapped
//     → The BNO055 axis map depends on how the chip is mounted on your breakout.
//       Use bno.setAxisRemap() / bno.setAxisSign() to correct orientation if needed.
//
//   Serial Plotter shows garbled / no traces
//     → Confirm baud rate in the plotter drop-down matches 115200.
//       Close Serial Monitor first — only one window can hold the port at a time.
// =============================================================================
