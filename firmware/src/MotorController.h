#pragma once
#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "PIDController.h"

// MotorController — one wheel: BTS7960 driver + quadrature encoder, closed-loop.
//
// inverted=true for the LEFT motor.  The left BTS7960 wiring and encoder mounting
// are both opposite to the right:
//   • Encoder: swapping A/B pins in firmware was not enough — the raw count still
//     goes negative for forward.  The inverted flag negates the delta so the PID
//     and telemetry always see +RPM = forward for both motors.
//   • Driver: LPWM = left forward, so duty must be negated before setSpeed() so
//     that setSpeed(negative) activates LPWM.
//
// maxRpm must match the motor's actual free-running RPM at full duty (255).
// Left free-run ≈ 200 RPM; right ≈ 120 RPM.

class MotorController {
public:
    static constexpr int TELEM_N = 25;  // 25 × 20 ms = 500 ms telemetry window

    MotorController(MotorDriver& driver, Encoder& encoder, int pulsesPerRev,
                    bool inverted = false, float maxRpm = MAX_RPM_RIGHT)
        : _driver(driver), _enc(encoder), _ppr(pulsesPerRev),
          _inverted(inverted), _maxRpm(maxRpm),
          _lastCount(0), _targetRPM(0.f), _actualRPM(0.f), _telemRPM(0.f),
          _accumDelta(0), _accumN(0),
          _pid(VEL_KP, VEL_KI, VEL_KD, -255.f, 255.f, VEL_ICLAMP) {}

    void begin() {
        _driver.begin();
        _lastCount = _enc.read();
    }

    // Call at 50 Hz (dt = 0.02 s) — reads encoder, runs PID, drives motor.
    void update(float dt) {
        const long count    = _enc.read();
        const long rawDelta = count - _lastCount;
        // Normalise so +delta = forward regardless of encoder mounting polarity.
        // The pin swap (23,22) alone was insufficient — raw still goes negative for
        // forward on the left motor, so we negate it here when inverted=true.
        const long delta    = _inverted ? -rawDelta : rawDelta;
        _lastCount = count;   // keep raw for accurate next-tick delta

        _actualRPM = ((float)delta / (float)_ppr) * (60.0f / dt);

        // 500 ms rolling average for telemetry only
        _accumDelta += delta;
        if (++_accumN >= TELEM_N) {
            _telemRPM   = ((float)_accumDelta / (float)_ppr) * (60.0f / (dt * TELEM_N));
            _accumDelta = 0;
            _accumN     = 0;
        }

        // Open-loop feed-forward: supplies ~95% of the needed duty instantly.
        // Without this, the integrator must wind up from zero before the motor
        // spins, causing slow start and windup that makes stopping unreliable.
        const float ffDuty = _targetRPM / _maxRpm * 255.0f;

        // PID correction on top of feed-forward (in normalised frame: +duty = forward)
        const float correction = _pid.compute(_targetRPM, _actualRPM, dt);

        const int duty = (int)constrain(ffDuty + correction, -255.f, 255.f);

        // Left motor: negate duty so setSpeed(negative) activates LPWM = forward.
        _driver.setSpeed(_inverted ? -duty : duty);
    }

    void setTargetRPM(float rpm) {
        _targetRPM = constrain(rpm, -_maxRpm, _maxRpm);
        if (fabsf(_targetRPM) < 0.1f) {
            _pid.reset();
            _driver.setSpeed(0);
        }
    }

    // Returns RPM in normalised frame: +positive = forward for both motors.
    float getActualRPM() const { return _telemRPM; }

    // Returns encoder count normalised to positive = forward.
    // DriveSystem.getAverageDistance() sums left + right directly, which requires
    // both to be in the same sign convention.
    long getEncoderCount() const { return _inverted ? -_lastCount : _lastCount; }

    void resetEncoder() {
        _enc.write(0);
        _lastCount  = 0;
        _accumDelta = 0;
        _accumN     = 0;
        _pid.reset();
    }

private:
    MotorDriver&  _driver;
    Encoder&      _enc;
    const int     _ppr;
    const bool    _inverted;
    const float   _maxRpm;
    long          _lastCount;
    float         _targetRPM;
    float         _actualRPM;
    float         _telemRPM;
    long          _accumDelta;
    int           _accumN;
    PIDController _pid;
};
