#pragma once
#include <Arduino.h>

// =============================================================================
// PIDController — generic, reusable PID with anti-windup and derivative-on-
// measurement (eliminates the derivative kick when the setpoint jumps).
//
// TUNING ORDER (applies to every PID layer — start inner before outer):
//   1. Set Ki = Kd = 0. Raise Kp until output oscillates, then back off ~30%.
//   2. Raise Kd until oscillations damp cleanly (typically 0.4–0.8 × Kp).
//   3. Add Ki only if steady-state error persists under constant load.
//      Keep iClamp tight (start at 10–20% of outMax) to limit windup.
// =============================================================================

class PIDController {
public:
    PIDController(float kp, float ki, float kd,
                  float outMin, float outMax, float iClamp)
        : _kp(kp), _ki(ki), _kd(kd),
          _outMin(outMin), _outMax(outMax), _iClamp(iClamp),
          _integral(0.f), _prevMeasurement(0.f), _firstRun(true) {}

    // compute() must be called at the cadence implied by dt (seconds).
    // Consistent dt is more important than a precise value — use a timer ISR.
    float compute(float setpoint, float measurement, float dt) {
        if (dt <= 0.f) return 0.f;

        const float error = setpoint - measurement;

        // P
        const float P = _kp * error;
        // I with clamp anti-windup: clamp the accumulator, not just the output.
        // This prevents the integrator from building up energy it cannot spend.
        _integral = constrain(_integral + error * dt, -_iClamp, _iClamp);
        const float I = _ki * _integral;

        // D on measurement — differentiate what the sensor sees, not the error.
        // A setpoint step no longer produces a derivative spike.
        const float dMeas = _firstRun ? 0.f : (measurement - _prevMeasurement) / dt;
        const float D     = -_kd * dMeas;

        _firstRun        = false;
        _prevMeasurement = measurement;

        return constrain(P + I + D, _outMin, _outMax);
    }

    void reset() {
        _integral        = 0.f;
        _firstRun        = true;
    }

    void setGains(float kp, float ki, float kd) { _kp = kp; _ki = ki; _kd = kd; }

private:
    float _kp, _ki, _kd;
    float _outMin, _outMax, _iClamp;
    float _integral;
    float _prevMeasurement;
    bool  _firstRun;
};
