// =============================================================================
// test_wheels_teensy — Stage 2: Dual BTS7960 Independent Motor Control
// Hardware : Teensy 4.1 (3.3V logic) + 2× BTS7960 43A H-bridge
// Motor    : 2× 775 DC 24V Planetary Gear Motor (120 RPM output)
// Power    : 24V supply (3A current limit recommended for first test)
//
// WIRING MAP
// ----------
// Right Motor — Driver 1:
//   BTS7960 RPWM → Teensy Pin 2  (PWM, forward direction)
//   BTS7960 LPWM → Teensy Pin 3  (PWM, reverse direction)
//   BTS7960 R_EN → Teensy Pin 4  (active-HIGH enable, forward half-bridge)
//   BTS7960 L_EN → Teensy Pin 5  (active-HIGH enable, reverse half-bridge)
//
// Left Motor — Driver 2:
//   BTS7960 RPWM → Teensy Pin 6  (PWM, forward direction)
//   BTS7960 LPWM → Teensy Pin 7  (PWM, reverse direction)
//   BTS7960 R_EN → Teensy Pin 8  (active-HIGH enable, forward half-bridge)
//   BTS7960 L_EN → Teensy Pin 9  (active-HIGH enable, reverse half-bridge)
//
// Both drivers share:
//   BTS7960 VCC  → Teensy 3.3V  (NOT 5V — Teensy 4.1 pins are not 5V tolerant)
//   BTS7960 GND  → Teensy GND + 24V supply −  (common ground is mandatory)
//   BTS7960 B+   → 24V supply +
//   BTS7960 B−   → 24V supply −  (shared GND rail)
//   BTS7960 M+/M−→ Motor terminals (swap M+/M− to reverse default spin direction)
//
// SAFETY NOTES
// ------------
//  • RPWM and LPWM are never driven HIGH simultaneously — MotorDriver::setSpeed()
//    zeros the inactive channel first before asserting the active one.
//  • BTS7960 VCC must be 3.3V so signal thresholds match Teensy's output levels.
//  • PWM frequency is set to 20 kHz to eliminate audible motor whine.
// =============================================================================

#include <Arduino.h>
#include "MotorDriver.h"

// --- Motor instances ---------------------------------------------------------
//  motorID 1 = Right Motor, Driver 1
static MotorDriver rightMotor(2, 3, 4, 5);

//  motorID 0 = Left Motor,  Driver 2
static MotorDriver leftMotor (6, 7, 8, 9);

// --- Test parameters ---------------------------------------------------------
static constexpr int          TARGET_PWM  = 100;  // Peak PWM for the test (0–255)
static constexpr int          RAMP_STEP   = 5;    // PWM increment per ramp tick
static constexpr unsigned long RAMP_MS    = 20;   // Delay between ramp ticks (ms)
static constexpr unsigned long HOLD_MS    = 2000; // Hold duration at peak speed (ms)
static constexpr unsigned long STOP_MS    = 1000; // Coast-stop duration (ms)

// --- Control interface -------------------------------------------------------
// motorID: 0 = left, 1 = right
// speed  : -255 (full reverse) … 0 (coast) … +255 (full forward)
// Shoot-through protection is enforced inside MotorDriver::setSpeed().
void setMotorSpeed(int motorID, int speed) {
    if (motorID == 0) {
        leftMotor.setSpeed(speed);
    } else {
        rightMotor.setSpeed(speed);
    }
}

// Convenience: set both motors to the same speed in one call
static void setBothMotors(int speed) {
    setMotorSpeed(0, speed);
    setMotorSpeed(1, speed);
}

// =============================================================================
void setup() {
    Serial.begin(115200);
    Serial.println("=== Dual BTS7960 Stage 2 test — starting ===");

    // begin() configures PWM frequency, sets pins OUTPUT, zeros speed, enables driver
    rightMotor.begin();
    leftMotor.begin();

    Serial.println("Both drivers enabled. Test loop starting in 1 s...");
    delay(1000);
}

// =============================================================================
void loop() {
    // --- Ramp forward: 0 → TARGET_PWM ---
    Serial.println("Ramp forward");
    for (int pwm = 0; pwm <= TARGET_PWM; pwm += RAMP_STEP) {
        setBothMotors(pwm);
        delay(RAMP_MS);
    }

    // --- Hold at peak forward speed ---
    Serial.print("Hold forward  PWM=");
    Serial.println(TARGET_PWM);
    setBothMotors(TARGET_PWM);
    delay(HOLD_MS);

    // --- Stop ---
    Serial.println("Stop");
    setBothMotors(0);
    delay(STOP_MS);

    // --- Ramp reverse: 0 → -TARGET_PWM ---
    Serial.println("Ramp reverse");
    for (int pwm = 0; pwm <= TARGET_PWM; pwm += RAMP_STEP) {
        setBothMotors(-pwm);
        delay(RAMP_MS);
    }

    // --- Hold at peak reverse speed ---
    Serial.print("Hold reverse  PWM=");
    Serial.println(-TARGET_PWM);
    setBothMotors(-TARGET_PWM);
    delay(HOLD_MS);

    // --- Stop ---
    Serial.println("Stop");
    setBothMotors(0);
    delay(STOP_MS);
}
