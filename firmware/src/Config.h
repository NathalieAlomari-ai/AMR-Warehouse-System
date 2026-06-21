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
// Formula: (encoder PPR on channel A) × 4 (full quadrature) × gear ratio
// Assuming 20 PPR magnetic encoder × 4 × 51:1 gearbox = 4080.
// VERIFY: spin output shaft one full turn by hand, Serial.print leftMotor.getEncoderCount().
static constexpr int   ENCODER_PPR       = 4080; // pulses per output shaft revolution

// Physical dimensions — measure your actual robot
static constexpr float WHEEL_DIAMETER_M  = 0.125f;   // metres  (65 mm example)
static constexpr float WHEEL_BASE_M      = 0.65f;    // metres  (wheel centre-to-centre)

// Derived — do not edit
static constexpr float WHEEL_CIRCUMF_M   = WHEEL_DIAMETER_M * 3.14159265f;
static constexpr float COUNTS_PER_METER  = (float)ENCODER_PPR / WHEEL_CIRCUMF_M;

// Maximum output-shaft RPM — clamps open-loop setpoints and scales duty cycle.
static constexpr float MAX_RPM           = 120.0f;
