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
static constexpr int   ENCODER_PPR       = 4;

// Physical dimensions — measure your actual robot
static constexpr float WHEEL_DIAMETER_M  = 0.125f;   // metres  (65 mm example)
static constexpr float WHEEL_BASE_M      = 0.65f;    // metres  (wheel centre-to-centre)

// Derived — do not edit
static constexpr float WHEEL_CIRCUMF_M   = WHEEL_DIAMETER_M * 3.14159265f;
static constexpr float COUNTS_PER_METER  = (float)ENCODER_PPR / WHEEL_CIRCUMF_M;

// Maximum believable output-shaft RPM (used to sanity-clamp velocity PID output)
static constexpr float MAX_RPM           = 120.0f;

// Velocity PID conservative baseline — tune from scratch, Ki last.
// With 4 PPR and a 200 ms measurement window, one quantisation step is ~30 RPM;
// gains above ~1.0 Kp will cause bang-bang oscillation at this resolution.
static constexpr float VEL_KP            = 0.05f;
static constexpr float VEL_KI            = 0.0f;
static constexpr float VEL_KD            = 0.0f;
static constexpr float VEL_ICLAMP        = 200.0f;
