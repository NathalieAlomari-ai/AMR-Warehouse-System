// =============================================================================
// main.cpp — AMR Cascade PID firmware for Teensy 4.1
//
// PIN ASSIGNMENT SUMMARY
// ----------------------
//  Right motor driver (BTS7960 #1):
//    RPWM=2  LPWM=3  R_EN=4  L_EN=5
//  Left motor driver (BTS7960 #2):
//    RPWM=6  LPWM=7  R_EN=8  L_EN=9
//  Right encoder:  A=20  B=21
//  Left  encoder:  A=22  B=23
//  BNO055 IMU:     SDA=18  SCL=19  (Teensy 4.1 hardware I2C, Wire)
//  Both BTS7960 VCC → Teensy 3.3V  (NOT 5V)
//  All GND rails commoned including 24V supply −
//
// SERIAL PROTOCOL  (USB CDC, 115200 baud)
//   Host → Teensy : "V <left_rpm> <right_rpm>\n"  (v or V)
//   Teensy → Host : "L_RPM:<f>\tR_RPM:<f>\tHdg:<f>\tDist:<f>\tLcnt:<i>\tRcnt:<i>\n"
//                    at 20 Hz
// =============================================================================

#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "MotorController.h"
#include "DriveSystem.h"

// ---------------------------------------------------------------------------
// Hardware objects — order of global construction matters:
//   Encoder objects attach their interrupts on construction.
//   MotorDriver/MotorController/DriveSystem call begin() in setup(), not here.
// ---------------------------------------------------------------------------

// BTS7960 drivers  (RPWM, LPWM, R_EN, L_EN)
MotorDriver rightDriver(2, 3, 4, 5);
MotorDriver leftDriver (6, 7, 8, 9);

// Quadrature encoders  (pin A, pin B)
// All Teensy 4.1 pins support external interrupts; the Encoder library uses them.
// Left encoder A/B are swapped so forward motion reads positive on both sides,
// matching the positive-RPM-forward convention used by serial_bridge_node.
Encoder rightEnc(20, 21);
Encoder leftEnc (23, 22);

MotorController rightMotor(rightDriver, rightEnc, ENCODER_PPR);
MotorController leftMotor (leftDriver,  leftEnc,  ENCODER_PPR);

DriveSystem drive(leftMotor, rightMotor);

// ---------------------------------------------------------------------------
// Timer interrupts
//   VelocityPID runs at 50 Hz (dt = 20 ms) — fast enough to control RPM.
//   Outer telemetry runs at 20 Hz (dt = 50 ms).
//   Flags are set in ISR and consumed in loop() to keep ISRs minimal.
// ---------------------------------------------------------------------------

IntervalTimer velTimer;
IntervalTimer outerTimer;

static constexpr float VEL_DT   = 1.0f / 50.0f;   // 20 ms
static constexpr float OUTER_DT = 1.0f / 20.0f;   // 50 ms

volatile bool velTick   = false;
volatile bool outerTick = false;

void FASTRUN onVelTimer()   { velTick   = true; }
void FASTRUN onOuterTimer() { outerTick = true; }

// ---------------------------------------------------------------------------
// Soft-brake / velocity ramp
//   The ramped setpoints (setRpmL/R) chase the commanded values (cmdRpmL/R)
//   at MAX_ACCEL RPM/s.  Both motors share the same rate so the PID on each
//   can compensate for individual friction — preventing yaw skew on the way
//   to zero.
//
//   MAX_ACCEL = 150 RPM/s → a motor at 150 RPM reaches 0 in exactly 1000 ms.
//   Lowered from 500 RPM/s to reduce gearbox backlash shock on motor startup,
//   which was causing wheel slip and corrupting encoder-derived odometry.
//   Raise to respond faster; lower for a gentler ramp.
// ---------------------------------------------------------------------------

static constexpr float    MAX_ACCEL      = 150.0f;   // RPM per second  (was 500.0f)
static constexpr uint32_t CMD_TIMEOUT_MS = 5000;      // watchdog: zero targets if silent

static float    cmdRpmL   = 0.f;   // last RPM commanded by Jetson (left)
static float    cmdRpmR   = 0.f;   // last RPM commanded by Jetson (right)
static float    setRpmL   = 0.f;   // current ramped setpoint fed into PID (left)
static float    setRpmR   = 0.f;   // current ramped setpoint fed into PID (right)
static uint32_t lastCmdMs = 0;

// ---------------------------------------------------------------------------
// Serial command buffer
// ---------------------------------------------------------------------------

static char    cmdBuf[64];
static uint8_t cmdLen = 0;

static void processCommand(const char* line) {
    if (toupper((unsigned char)line[0]) != 'V') return;
    float l = 0.f, r = 0.f;
    if (sscanf(line + 1, " %f %f", &l, &r) != 2) return;
    cmdRpmL   = l;
    cmdRpmR   = r;
    lastCmdMs = millis();
}

// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== AMR ROS2 Listener — booting ===");

    if (!drive.begin()) {
        Serial.println("FATAL: BNO055 IMU not found. Check I2C wiring (SDA=18, SCL=19) and VCC=3.3V.");
        while (true) delay(500);
    }
    Serial.println("IMU OK. Waiting for velocity commands...");

    lastCmdMs = millis();

    // Start timers — period in microseconds
    velTimer.begin(onVelTimer,     1000000U / 50U);   // 50 Hz
    outerTimer.begin(onOuterTimer, 1000000U / 20U);   // 20 Hz
}

// ---------------------------------------------------------------------------
void loop() {
    uint32_t now = millis();

    // ── Serial receive ────────────────────────────────────────────────────────
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (cmdLen > 0) {
                cmdBuf[cmdLen] = '\0';
                processCommand(cmdBuf);
                cmdLen = 0;
            }
        } else if (cmdLen < (uint8_t)(sizeof(cmdBuf) - 1)) {
            cmdBuf[cmdLen++] = c;
        }
    }

    // ── Watchdog — zero targets if Jetson goes silent ─────────────────────────
    if (now - lastCmdMs > CMD_TIMEOUT_MS) {
        cmdRpmL   = 0.f;
        cmdRpmR   = 0.f;
        lastCmdMs = now;   // re-arm: triggers once per CMD_TIMEOUT_MS, not every tick
    }

    // ── velTick — 50 Hz — soft-brake ramp + velocity PID ─────────────────────
    if (velTick) {
        velTick = false;

        // Ramp each setpoint toward its commanded value at MAX_ACCEL RPM/s
        const float step = MAX_ACCEL * VEL_DT;

        float errL = cmdRpmL - setRpmL;
        setRpmL = (fabsf(errL) <= step) ? cmdRpmL : setRpmL + (errL > 0.f ? step : -step);

        float errR = cmdRpmR - setRpmR;
        setRpmR = (fabsf(errR) <= step) ? cmdRpmR : setRpmR + (errR > 0.f ? step : -step);

        leftMotor.setTargetRPM(setRpmL);
        rightMotor.setTargetRPM(setRpmR);
        leftMotor.update(VEL_DT);
        rightMotor.update(VEL_DT);
    }

    // ── outerTick — 20 Hz — telemetry for ROS 2 bridge ───────────────────────
    if (outerTick) {
        outerTick = false;

        // Telemetry — parse with Serial Plotter or a host-side logger
        Serial.print("L_RPM:");    Serial.print(leftMotor.getActualRPM(),  1);
        Serial.print("\tR_RPM:");  Serial.print(rightMotor.getActualRPM(), 1);
        Serial.print("\tHdg:");    Serial.print(drive.getHeadingDeg(),      1);
        Serial.print("\tDist:");   Serial.print(drive.getAverageDistance(), 3);
        Serial.print("\tLcnt:");   Serial.print(leftMotor.getEncoderCount());
        Serial.print("\tRcnt:");   Serial.println(rightMotor.getEncoderCount());
    }
}
