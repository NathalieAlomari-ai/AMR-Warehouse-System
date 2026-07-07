#pragma once

// =============================================================================
// Config.h — Robot physical constants. Edit here; nowhere else.
//
// HOW TO MEASURE ENCODER_PPR:
//   Mark the output shaft. Spin it one full revolution by hand.
//   Count the raw pulses on channel A with a scope or Serial.print in setup().
//   Multiply by 4 for quadrature. That number is ENCODER_PPR.
//   Typical 775-class planetary motor: (11 encoder lines × 4) × 30:1 = 1320.
// =============================================================================

// Encoder pulses per full revolution of the OUTPUT shaft (after gearbox).
static constexpr int   ENCODER_PPR       = 2700;

// Physical dimensions — measure your actual robot
static constexpr float WHEEL_DIAMETER_M  = 0.125f;   // metres
static constexpr float WHEEL_BASE_M      = 0.65f;    // metres (wheel centre-to-centre)

// Derived — do not edit
static constexpr float WHEEL_CIRCUMF_M   = WHEEL_DIAMETER_M * 3.14159265f;
static constexpr float COUNTS_PER_METER  = (float)ENCODER_PPR / WHEEL_CIRCUMF_M;

// Free-run max RPM at full duty (255) — measured from telemetry on the floor:
//   Left:  FF duty = target/75×255 = 104  →  actual 62.7 RPM  →  max = 62.7×255/104 ≈ 154
//   Right: FF duty = target/60×255 = 130  →  actual 75.7 RPM  →  max = 75.7×255/130 ≈ 149
// Both motors measure ~150 RPM free-run max.  Using one shared value means
// both motors receive identical FF duty for any target, so the PID only needs
// to trim the small difference caused by per-motor friction.
//
// HOW TO RECALIBRATE if motors feel sluggish or over-fast:
//   Drive at a steady speed, note telemetry RPM and the telemetry duty (add
//   'duty' to Serial.print in main.cpp if needed).
//   MAX_RPM = observed_RPM × 255 / observed_duty
static constexpr float MAX_RPM_LEFT      = 150.0f;
static constexpr float MAX_RPM_RIGHT     = 150.0f;

// Velocity PID gains.
// Kp: immediate proportional correction to RPM error.
// Ki: integrates away persistent motor-to-motor differences (floor friction etc.).
// Kd: keep at 0 — derivative on per-tick encoder counts is pure noise.
//
// Tuning guide:
//   Still drifts after 3 s   → raise Ki (try 1.5)
//   Motors oscillate/shake   → lower Kp (try 0.5)
//   Slow to correct          → raise Kp (try 1.2)
static constexpr float VEL_KP            = 0.8f;
static constexpr float VEL_KI            = 1.0f;
static constexpr float VEL_KD            = 0.0f;
// With MAX_RPM calibrated to true free-run, FF is accurate and residual
// error is only 3–8 RPM (floor friction difference between motors).
// ICLAMP=30 provides up to 30 duty units of integral correction — plenty.
static constexpr float VEL_ICLAMP        = 30.0f;

// =============================================================================
// Lift (scissor linear actuator) — BTS7960 + 1 limit switch.
//
// Pins per docs/HANDOFF_zahra_firmware.md — the ESP32 test sketch reused pins
// 18/19/21/22/32, which on this Teensy are already the BNO055 I2C bus and the
// quadrature encoders. These are the re-mapped, conflict-free pins.
//
// No top limit switch: full-range (min retracted -> max extended) timing was
// bench-verified directly on the assembled scissor lift, so the top switch was
// dropped as an unneeded failsafe. The bottom switch stays — it's not really a
// safety switch, it's the only re-homing reference in the system. Every
// "LIFT 0" retracts until it fires, which bounds the open-loop drift that
// would otherwise accumulate across a long mission's repeated partial moves
// (e.g. shelf 200 -> home 0 -> drop-off 120 -> home 0 -> ...).
// =============================================================================
static constexpr int   LIFT_RPWM         = 28;   // extend  (PWM)
static constexpr int   LIFT_LPWM         = 29;   // retract (PWM)
static constexpr int   LIFT_REN          = 30;
static constexpr int   LIFT_LEN          = 31;
static constexpr int   LIFT_BOTTOM       = 34;   // 0 mm / home limit switch

// Measured on the bench (open-loop, no encoder on the actuator itself —
// position is estimated from commanded run time and re-zeroed whenever the
// bottom limit switch fires). LIFT_MAX_TRAVEL_MM is a software-only clamp
// now (no top switch backs it up), so a bad command can't ask for a mm value
// beyond the rail's physical length.
static constexpr float ACTUATOR_SPEED_MM_S  = 5.0f;
static constexpr float LIFT_MAX_TRAVEL_MM   = 250.0f;
