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

// Maximum believable output-shaft RPM (used to sanity-clamp velocity PID output)
static constexpr float MAX_RPM           = 120.0f;

// Velocity PID — with 4 PPR and a 200 ms window one quantisation step ≈ 30 RPM.
// Ki is the primary steady-state corrector: it integrates away the persistent
// speed difference caused by each motor's unique friction and back-EMF, something
// a P-only controller can never do.  Kp gives a fast initial kick; Kd stays 0
// because derivative on step-like quantised feedback is pure noise.
//
// Starting point: Kp=0.10, Ki=2.0.  If a motor oscillates (hunts), halve Ki first.
// If steady-state error persists, double Ki.  Raise Kp only if response is sluggish.
static constexpr float VEL_KP            = 0.8f;
static constexpr float VEL_KI            = 0.0f;
static constexpr float VEL_KD            = 0.0f;
static constexpr float VEL_ICLAMP        = 200.0f;
