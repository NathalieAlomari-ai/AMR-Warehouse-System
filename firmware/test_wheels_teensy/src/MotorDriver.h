#pragma once
#include <Arduino.h>

// =============================================================================
// MotorDriver — BTS7960 43A H-bridge HAL.
//
// WIRING (per driver, repeat for each side):
//   BTS7960 VCC  → Teensy 3.3V  (NOT 5V — Teensy 4.1 pins are not 5V tolerant)
//   BTS7960 GND  → Teensy GND   (must share common ground with 24V supply −)
//   BTS7960 RPWM → Teensy PWM pin (forward direction)
//   BTS7960 LPWM → Teensy PWM pin (reverse direction)
//   BTS7960 R_EN → Teensy digital pin (active-HIGH enable, forward half-bridge)
//   BTS7960 L_EN → Teensy digital pin (active-HIGH enable, reverse half-bridge)
//   BTS7960 B+   → 24V supply +
//   BTS7960 B−   → 24V supply − (= shared GND rail)
//   BTS7960 M+/M−→ Motor terminals (swap to reverse default direction)
//
// NOTE: RPWM and LPWM are never both non-zero simultaneously here; the
// shoot-through guard in setSpeed() ensures this at the driver level.
// =============================================================================

class MotorDriver {
public:
    MotorDriver(int rpwm, int lpwm, int ren, int len, int pwmFreq = 20000)
        : _rpwm(rpwm), _lpwm(lpwm), _ren(ren), _len(len), _pwmFreq(pwmFreq) {}

    void begin() {
        // Set frequency before pinMode so the timer is configured before the pin is driven
        analogWriteFrequency(_rpwm, _pwmFreq);
        analogWriteFrequency(_lpwm, _pwmFreq);
        pinMode(_rpwm, OUTPUT);
        pinMode(_lpwm, OUTPUT);
        pinMode(_ren,  OUTPUT);
        pinMode(_len,  OUTPUT);
        setSpeed(0);
        enable(true);
    }

    // speed: −255 (full reverse) … 0 (coast) … +255 (full forward)
    void setSpeed(int speed) {
        speed = constrain(speed, -255, 255);
        if (speed > 0) {
            analogWrite(_lpwm, 0);       // zero inactive channel FIRST (shoot-through guard)
            analogWrite(_rpwm, speed);
        } else if (speed < 0) {
            analogWrite(_rpwm, 0);
            analogWrite(_lpwm, -speed);
        } else {
            analogWrite(_rpwm, 0);
            analogWrite(_lpwm, 0);
        }
    }

    void enable(bool on) {
        digitalWrite(_ren, on ? HIGH : LOW);
        digitalWrite(_len, on ? HIGH : LOW);
    }

    void stop() { setSpeed(0); }

private:
    const int _rpwm, _lpwm, _ren, _len, _pwmFreq;
};
