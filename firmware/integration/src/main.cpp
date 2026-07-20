// =============================================================================
// main.cpp — AMR unified firmware for Teensy 4.1 (drive PID + odometry + lift)
//
// PIN ASSIGNMENT SUMMARY
// ----------------------
//  Right motor driver (BTS7960 #1):
//    RPWM=2  LPWM=3  R_EN=4  L_EN=5
//  Left motor driver (BTS7960 #2):
//    RPWM=6  LPWM=7  R_EN=8  L_EN=9
//  Right encoder:  A=20  B=21
//  Left  encoder:  A=22  B=23  (A/B swapped so forward reads +positive —
//                  corrected from an initial A=23/B=22 wiring that read backward)
//  BNO055 IMU:     SDA=18  SCL=19  (Teensy 4.1 hardware I2C, Wire)
//  Both BTS7960 VCC → Teensy 3.3V  (NOT 5V)
//  All GND rails commoned including 24V supply −
//
//  Lift BTS7960 (scissor actuator) — see Config.h / docs/HANDOFF_zahra_firmware.md:
//    RPWM=28  LPWM=29  R_EN=30  L_EN=31  bottom-limit=34
//    No top limit switch: full-range timing was bench-verified on the
//    assembled scissor lift, so only the bottom (re-homing) switch is wired.
//
//  Stepper carriage (TB6600) + vacuum gripper (relays) — see Config.h:
//    STEP=36  DIR=37  home-limit=32  max-limit=33
//    Pump relay=40  Valve relay=41
//    Wired common-cathode (PUL+/DIR+ -> Teensy, PUL-/DIR- -> common GND).
//    TB6600 DIP switches: SW4=ON SW5=ON SW6=OFF (1/16 microstep, required);
//    SW1-3 set current, match to the stepper's rated current.
//
//  Full power/wiring guide (thick vs thin wire, grounding, DIP switch
//  tables, per-driver pinout) is in README.md → "Power & wiring guide".
//
// SERIAL PROTOCOL  (USB CDC, 115200 baud)
//   Host → Teensy : "V <left_rpm> <right_rpm>\n"  (v or V) — drive
//                    "LIFT <mm>\n"                          — move lift to absolute height
//                    "PICK\n"                                — move lift to the fixed pick
//                                                               height (PICK_LIFT_MM, Config.h)
//                    "DROP\n"                                — move lift to the fixed drop-off
//                                                               height (DROP_LIFT_MM, Config.h)
//                    "STEP EXT\n"                            — extend carriage to the max limit
//                    "STEP RET\n"                            — retract carriage to the home limit
//                    "PUMP ON\n"                             — engage vacuum (valve open -> pump on)
//                    "PUMP OFF\n"                            — release vacuum (pump off -> valve vent)
//                    "STOP\n"                                — halt drive + lift + stepper immediately
//                                                               (does NOT release the pump/valve —
//                                                               see PumpControl::stop())
//                    (SERVO: not yet implemented — ignored)
//   Teensy → Host : "L_RPM:<f>\tR_RPM:<f>\tHdg:<f>\tDist:<f>\tLcnt:<i>\tRcnt:<i>\n"
//                    at 20 Hz — unchanged, byte-for-byte, so the ROS bridge's
//                    odometry parser is untouched.
//                    "EVT LIFT DONE" on its own line whenever a lift move finishes.
//                    "EVT STEP DONE" whenever a stepper extend/retract finishes.
//                    "EVT PUMP ON" / "EVT PUMP OFF" whenever the gripper finishes.
// =============================================================================

#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "MotorController.h"
#include "DriveSystem.h"
#include "LiftControl.h"
#include "StepperControl.h"
#include "PumpControl.h"

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
// (A=22/B=23 — bench testing found the initial A=23/B=22 wiring counted backward.)
Encoder rightEnc(20, 21);
Encoder leftEnc (22, 23);

// motorInverted=true on BOTH sides: bench testing (equal-target 'i' command
// still rotating the robot instead of driving straight, after the left encoder
// wiring was already fixed) showed the right BTS7960 is also wired with RPWM as
// the REVERSE direction, not forward as originally assumed — the right wheel
// visibly spun backward under a positive target until this was flipped too.
// maxRpm differs because the two motors have different free-running speeds at
// full duty — see MAX_RPM_LEFT / MAX_RPM_RIGHT in Config.h.
MotorController rightMotor(rightDriver, rightEnc, ENCODER_PPR, true, MAX_RPM_RIGHT);
MotorController leftMotor (leftDriver,  leftEnc,  ENCODER_PPR, true,  MAX_RPM_LEFT);

DriveSystem drive(leftMotor, rightMotor);

// Scissor-lift actuator — see LiftControl.h / Config.h for pins & protocol.
LiftControl lift;

// Suction-cup carriage + vacuum gripper — see StepperControl.h/PumpControl.h.
StepperControl stepperCarriage;
PumpControl    pump;

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
    if (toupper((unsigned char)line[0]) == 'V') {
        float l = 0.f, r = 0.f;
        if (sscanf(line + 1, " %f %f", &l, &r) != 2) return;
        cmdRpmL   = l;
        cmdRpmR   = r;
        lastCmdMs = millis();
        return;
    }

    if (!strncmp(line, "LIFT ", 5)) {
        lift.moveToMm((float)atof(line + 5));
        lastCmdMs = millis();
        return;
    }

    // Fixed presentation heights — Teensy owns the target mm, not the Jetson.
    if (!strcmp(line, "PICK")) {
        lift.moveToMm(PICK_LIFT_MM);
        lastCmdMs = millis();
        return;
    }

    if (!strcmp(line, "DROP")) {
        lift.moveToMm(DROP_LIFT_MM);
        lastCmdMs = millis();
        return;
    }

    if (!strcmp(line, "STEP EXT")) {
        stepperCarriage.extend();
        lastCmdMs = millis();
        return;
    }

    if (!strcmp(line, "STEP RET")) {
        stepperCarriage.retract();
        lastCmdMs = millis();
        return;
    }

    if (!strcmp(line, "PUMP ON")) {
        pump.pumpOn();
        lastCmdMs = millis();
        return;
    }

    if (!strcmp(line, "PUMP OFF")) {
        pump.pumpOff();
        lastCmdMs = millis();
        return;
    }

    if (!strcmp(line, "STOP")) {
        lift.stop();
        stepperCarriage.stop();
        cmdRpmL = 0.f;
        cmdRpmR = 0.f;
        lastCmdMs = millis();
        return;
    }

    // "SERVO <deg>": not implemented — vision's job, mission completes without
    // it. Falls through and is ignored, same as any other unrecognized line.
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

    lift.begin();             // homes the lift so its position estimate starts accurate
    stepperCarriage.begin();  // homes the carriage against the bottom limit switch
    pump.begin();

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

    // ── Lift / stepper / pump state machines — non-blocking, must run every pass ──
    lift.update();
    stepperCarriage.update();
    pump.update();

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
