#pragma once
#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "PIDController.h"

// =============================================================================
// MotorController — one wheel: BTS7960 driver + quadrature encoder + velocity PID.
//
// VELOCITY PID TUNING (tune this layer FIRST, before any outer loop):
//   Target: motor reaches commanded RPM within ~2 counts (≈40 ms at 50 Hz).
//   1. Ki = Kd = 0. Raise Kp until RPM oscillates under step command, back off 30%.
//   2. Add Kd (start 0.01) to damp oscillation.
//   3. Add Ki (start 0.1) only if there is persistent RPM error under load.
//   4. Keep iClamp ≤ 30% of outMax to prevent windup on direction reversal.
//
// ENCODER WIRING:
//   Encoder A → interrupt pin   (all Teensy 4.1 pins are interrupt-capable)
//   Encoder B → interrupt pin   (choose adjacent pin for easy wiring)
//   Encoder VCC → Teensy 3.3V
//   Encoder GND → Teensy GND
// =============================================================================

class MotorController {
public:
    // velPID output limits: ±255 maps directly to analogWrite duty cycle.
    // Default gains are a starting point — tune on your hardware.
    MotorController(MotorDriver& driver, Encoder& encoder, int pulsesPerRev)
        : _driver(driver), _enc(encoder), _ppr(pulsesPerRev),
          velPID(/*kp*/1.0f, /*ki*/0.3f, /*kd*/0.02f,
                 /*outMin*/-255.f, /*outMax*/255.f, /*iClamp*/80.f),
          _lastCount(0), _actualRPM(0.f), _targetRPM(0.f) {}

    void begin() {
        _driver.begin();
        _lastCount = _enc.read();
    }

    // Call from a 50 Hz IntervalTimer ISR (or set velTick flag and call from loop).
    // dt must match the actual call period in seconds.
    void update(float dt) {
        const long count = _enc.read();
        const long delta = count - _lastCount;
        _lastCount = count;

        // RPM of the output shaft
        _actualRPM = ((float)delta / (float)_ppr) * (60.0f / dt);

        const float output = velPID.compute(_targetRPM, _actualRPM, dt);
        _driver.setSpeed((int)output);
    }

    void setTargetRPM(float rpm) {
        _targetRPM = constrain(rpm, -MAX_RPM, MAX_RPM);
    }

    float getActualRPM()    const { return _actualRPM;  }
    long  getEncoderCount() const { return _lastCount;  }

    void resetEncoder() {
        _enc.write(0);
        _lastCount = 0;
        velPID.reset();
    }

    PIDController velPID;

private:
    MotorDriver& _driver;
    Encoder&     _enc;
    const int    _ppr;
    long         _lastCount;
    float        _actualRPM;
    float        _targetRPM;
};
