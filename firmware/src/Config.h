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
