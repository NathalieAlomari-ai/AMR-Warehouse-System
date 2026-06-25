#pragma once
#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "PIDController.h"

// MotorController — one wheel: BTS7960 driver + quadrature encoder, closed-loop.
//
// setTargetRPM() stores the desired speed. update() runs the PID every 20 ms,
// reads the encoder, and adjusts PWM so actual RPM tracks the target.
// This compensates for per-motor friction and back-EMF differences that cause
// open-loop robots to veer.

class MotorController {
public:
    static constexpr int TELEM_N = 25;  // 25 × 20 ms = 500 ms telemetry window

    MotorController(MotorDriver& driver, Encoder& encoder, int pulsesPerRev)
        : _driver(driver), _enc(encoder), _ppr(pulsesPerRev),
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

        // Per-tick RPM for closed-loop control
        _actualRPM = ((float)delta / (float)_ppr) * (60.0f / dt);

        // 500 ms rolling average for telemetry only
        _accumDelta += delta;
        if (++_accumN >= TELEM_N) {
            _telemRPM   = ((float)_accumDelta / (float)_ppr) * (60.0f / (dt * TELEM_N));
            _accumDelta = 0;
            _accumN     = 0;
        }

        // Closed-loop: PID adjusts PWM based on actual vs target RPM
        const int duty = (int)_pid.compute(_targetRPM, _actualRPM, dt);
        _driver.setSpeed(duty);
    }

    // Store target; PID runs in update(). Resets integrator when stopping
    // to prevent integral windup carrying over to the next move.
    void setTargetRPM(float rpm) {
        _targetRPM = constrain(rpm, -MAX_RPM, MAX_RPM);
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
    long          _lastCount;
    float         _targetRPM;
    float         _actualRPM;
    float         _telemRPM;
    long          _accumDelta;
    int           _accumN;
    PIDController _pid;
};
