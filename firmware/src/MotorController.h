#pragma once
#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "PIDController.h"

// MotorController — one wheel: BTS7960 driver + quadrature encoder, closed-loop.
//
// motorInverted=true for the LEFT motor: the BTS7960 wiring makes LPWM the forward
// direction for the left wheel (opposite of the right), so the duty sign must be
// negated before calling setSpeed().  The encoder pin swap (23, 22) already ensures
// both encoders read +positive for forward, so this flag only affects the driver.
//
// maxRpm must match the motor's actual free-running RPM at full duty (255).
// It scales the open-loop feed-forward.  Left motor free-run ≈ 200 RPM;
// right ≈ 120 RPM.  An under-estimated value over-drives the motor on spin-up.

class MotorController {
public:
    static constexpr int TELEM_N = 25;  // 25 × 20 ms = 500 ms telemetry window

    MotorController(MotorDriver& driver, Encoder& encoder, int pulsesPerRev,
                    bool motorInverted = false, float maxRpm = MAX_RPM_RIGHT)
        : _driver(driver), _enc(encoder), _ppr(pulsesPerRev),
          _motorInverted(motorInverted), _maxRpm(maxRpm),
          _lastCount(0), _targetRPM(0.f), _actualRPM(0.f), _telemRPM(0.f),
          _accumDelta(0), _accumN(0),
          _pid(VEL_KP, VEL_KI, VEL_KD, -255.f, 255.f, VEL_ICLAMP) {}

    void begin() {
        _driver.begin();
        _lastCount = _enc.read();
    }

    // Call at 50 Hz (dt = 0.02 s) — reads encoder, runs PID, drives motor.
    void update(float dt) {
        const long count = _enc.read();
        const long delta = count - _lastCount;
        _lastCount = count;

        // Per-tick RPM for closed-loop control (both encoders positive = forward)
        _actualRPM = ((float)delta / (float)_ppr) * (60.0f / dt);

        // 500 ms rolling average for telemetry only
        _accumDelta += delta;
        if (++_accumN >= TELEM_N) {
            _telemRPM   = ((float)_accumDelta / (float)_ppr) * (60.0f / (dt * TELEM_N));
            _accumDelta = 0;
            _accumN     = 0;
        }

        // Open-loop feed-forward: supplies ~95% of the needed duty instantly so the
        // PID only needs to trim the residual error (usually < 10 RPM).
        // Without this, the integrator must wind up from zero before the motor spins,
        // causing slow start and severe windup that makes stopping unreliable.
        const float ffDuty = _targetRPM / _maxRpm * 255.0f;

        // PID correction on top of feed-forward
        const float correction = _pid.compute(_targetRPM, _actualRPM, dt);

        const int duty = (int)constrain(ffDuty + correction, -255.f, 255.f);

        // Left motor (motorInverted=true): LPWM = forward, so negate duty so that
        // setSpeed(negative) activates LPWM.  Right motor: setSpeed(positive) = RPWM = forward.
        _driver.setSpeed(_motorInverted ? -duty : duty);
    }

    // Store target; PID runs in update(). Resets integrator when stopping
    // to prevent integral windup carrying over to the next move.
    void setTargetRPM(float rpm) {
        _targetRPM = constrain(rpm, -_maxRpm, _maxRpm);
        if (fabsf(_targetRPM) < 0.1f) {
            _pid.reset();
            _driver.setSpeed(0);
        }
    }

    float getActualRPM()    const { return _telemRPM; }
    long  getEncoderCount() const { return _lastCount; }

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
    const bool    _motorInverted;
    const float   _maxRpm;
    long          _lastCount;
    float         _targetRPM;
    float         _actualRPM;
    float         _telemRPM;
    long          _accumDelta;
    int           _accumN;
    PIDController _pid;
};
