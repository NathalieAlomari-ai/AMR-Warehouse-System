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
// Hardware measured: 20-pulse magnetic encoder through planetary gearbox → 4 ticks/wheel-rev
// (confirmed with scope at 5 V supply; was previously mis-set to 1320).
static constexpr int   ENCODER_PPR       = 2700;

// Physical dimensions — measure your actual robot
static constexpr float WHEEL_DIAMETER_M  = 0.125f;   // metres  (65 mm example)
static constexpr float WHEEL_BASE_M      = 0.65f;    // metres  (wheel centre-to-centre)

// Derived — do not edit
static constexpr float WHEEL_CIRCUMF_M   = WHEEL_DIAMETER_M * 3.14159265f;
static constexpr float COUNTS_PER_METER  = (float)ENCODER_PPR / WHEEL_CIRCUMF_M;

// Per-motor free-running max RPM at full duty (measured: duty=170/255 drove left at
// 132 RPM → free-run max = 132×255/170 ≈ 200; right at ~77 RPM → ≈ 116 ≈ 120).
// Scales the open-loop feed-forward in MotorController. An under-estimated value
// over-drives the motor; an over-estimated value under-drives it.
static constexpr float MAX_RPM_LEFT      = 200.0f;
static constexpr float MAX_RPM_RIGHT     = 120.0f;

// Velocity PID gains.
// Kp gives an immediate proportional correction to RPM error.
// Ki integrates away the persistent offset between motors (friction, back-EMF).
// Kd stays 0: derivative on per-tick encoder counts is pure noise.
//
// Tuning guide:
//   Still drifts after 2–3 s  → raise Ki (try 2.0)
//   Motors oscillate/shake    → lower Kp (try 0.5)
//   Sluggish speed correction → raise Kp (try 1.2)
//   One motor runs at max     → VEL_ICLAMP still too high; halve it
static constexpr float VEL_KP            = 0.8f;
static constexpr float VEL_KI            = 1.0f;
static constexpr float VEL_KD            = 0.0f;
// Clamp on the integral accumulator (RPM·s).  Keep small — the feed-forward
// already provides ~95% of the needed duty; the integral only corrects residual
// error (~5–10 RPM).  Large values cause windup and make stopping unreliable.
static constexpr float VEL_ICLAMP        = 20.0f;
