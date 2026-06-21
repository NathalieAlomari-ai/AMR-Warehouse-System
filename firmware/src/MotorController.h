#pragma once
#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"

// MotorController — one wheel: BTS7960 driver + quadrature encoder, open-loop.
//
// setTargetRPM() maps the requested RPM linearly to a PWM duty cycle [-255, 255]
// using MAX_RPM as the full-scale reference. No feedback is applied.
// RPM reported by getActualRPM() is for telemetry only (averaged over 500 ms).

class MotorController {
public:
    static constexpr int RPM_WINDOW_N = 25;  // 25 × 20 ms = 500 ms averaging window

    MotorController(MotorDriver& driver, Encoder& encoder, int pulsesPerRev)
        : _driver(driver), _enc(encoder), _ppr(pulsesPerRev),
          _lastCount(0), _actualRPM(0.f),
          _accumDelta(0), _accumN(0) {}

    void begin() {
        _driver.begin();
        _lastCount = _enc.read();
    }

    // Call at 50 Hz to keep the telemetry RPM estimate fresh. dt in seconds.
    void update(float dt) {
        const long count = _enc.read();
        const long delta = count - _lastCount;
        _lastCount = count;

        _accumDelta += delta;
        _accumN++;
        if (_accumN >= RPM_WINDOW_N) {
            const float windowSec = dt * (float)RPM_WINDOW_N;
            _actualRPM = ((float)_accumDelta / (float)_ppr) * (60.0f / windowSec);
            _accumDelta = 0;
            _accumN     = 0;
        }
    }

    // Open-loop: maps rpm linearly to duty cycle and drives the motor immediately.
    void setTargetRPM(float rpm) {
        rpm = constrain(rpm, -MAX_RPM, MAX_RPM);
        const int duty = (int)(rpm / MAX_RPM * 255.0f);
        _driver.setSpeed(duty);
    }

    float getActualRPM()    const { return _actualRPM; }
    long  getEncoderCount() const { return _lastCount; }

    void resetEncoder() {
        _enc.write(0);
        _lastCount  = 0;
        _accumDelta = 0;
        _accumN     = 0;
    }

private:
    MotorDriver& _driver;
    Encoder&     _enc;
    const int    _ppr;
    long         _lastCount;
    float        _actualRPM;
    long         _accumDelta;
    int          _accumN;
};
