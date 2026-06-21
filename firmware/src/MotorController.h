#pragma once
#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "PIDController.h"

// =============================================================================
// MotorController — one wheel: BTS7960 driver + quadrature encoder + velocity PID.
//
// LOW-RESOLUTION ENCODER STRATEGY (4 PPR):
//   At 4 ticks/rev and a 50 Hz PID, the expected tick count per 20 ms interval
//   is < 1 at normal speeds — so instantaneous RPM is always 0.0.  The fix is
//   to accumulate ticks over WINDOW_CYCLES intervals (200 ms) before computing
//   RPM, then smooth the coarse step-like result with an EMA filter.
//
// VELOCITY PID GAINS (4 PPR, 200 ms measurement window):
//   Kd = 0  — derivative on step-like feedback is pure quantisation noise.
//   Ki      — primary steady-state corrector; integral tracks the true average
//              even when individual window readings jump between quantisation
//              levels (e.g. 75 RPM ↔ 150 RPM for a true 120 RPM motor).
//   Kp      — proportional kick when a window shows a meaningful RPM deviation.
//   iClamp  — wide enough to absorb large mechanical asymmetry between wheels.
//
// TUNING ORDER:
//   1. Set Ki = 0.  Raise Kp until each wheel tracks its target within one
//      quantisation step (30 RPM with 4 PPR / 200 ms window).  Back off 20%.
//   2. Add Ki (start 1.0) until steady-state error under load disappears.
//      Watch that iClamp prevents windup on direction reversal.
//   3. Leave Kd = 0 unless you replace the EMA with a proper observer.
//
// ENCODER WIRING:
//   Encoder A → interrupt pin   (all Teensy 4.1 pins are interrupt-capable)
//   Encoder B → interrupt pin
//   Encoder VCC → 5 V   (3.3 V undersupply caused missing pulses — use 5 V)
//   Encoder GND → Teensy GND
// =============================================================================

// Number of 50 Hz VEL_DT cycles to accumulate before computing RPM.
// 10 cycles × 20 ms = 200 ms window.  At 4 PPR / 120 RPM this yields
// ~1–2 ticks per window; EMA then smooths the quantisation steps.
static constexpr int WINDOW_CYCLES = 10;

class MotorController {
public:
    // velPID output limits: ±255 maps directly to analogWrite duty cycle.
    MotorController(MotorDriver& driver, Encoder& encoder, int pulsesPerRev)
        : _driver(driver), _enc(encoder), _ppr(pulsesPerRev),
          velPID(VEL_KP, VEL_KI, VEL_KD,
                 /*outMin*/-255.f, /*outMax*/255.f, /*iClamp*/VEL_ICLAMP),
          _lastCount(0), _actualRPM(0.f), _targetRPM(0.f),
          _accTicks(0), _accCycles(0) {}

    void begin() {
        _driver.begin();
        _lastCount = (int32_t)_enc.read();
    }

    // Called at 50 Hz.  Ticks accumulate every call; RPM and PID update once
    // per WINDOW_CYCLES calls (every 200 ms).  The motor driver holds its last
    // commanded PWM between window boundaries — no extra call needed.
    void update(float dt) {
        // Immediate stop — do not wait for the window to complete.
        // Refresh _lastCount so the first delta after re-enabling is clean.
        if (_targetRPM == 0.f) {
            _lastCount = (int32_t)_enc.read();
            _driver.setSpeed(0);
            _actualRPM = 0.f;
            _accTicks  = 0;
            _accCycles = 0;
            velPID.reset();
            return;
        }

        const int32_t count = (int32_t)_enc.read();
        const int32_t delta = count - _lastCount;
        _lastCount = count;

        _accTicks  += delta;
        _accCycles++;

        if (_accCycles >= WINDOW_CYCLES) {
            const float windowDt = dt * (float)_accCycles;

            // Raw RPM from accumulated ticks over the full window
            const float rawRPM = ((float)_accTicks / (float)_ppr) * (60.0f / windowDt);

            // EMA (α = 0.4): damps the step-like jumps between quantisation
            // levels while remaining responsive to real speed changes.
            _actualRPM = 0.4f * rawRPM + 0.6f * _actualRPM;

            _accTicks  = 0;
            _accCycles = 0;

            // PID runs at the window rate (5 Hz), not at 50 Hz, so the
            // integral accumulates at the correct rate for windowDt.
            const float output = velPID.compute(_targetRPM, _actualRPM, windowDt);
            _driver.setSpeed((int)output);
        }
    }

    void setTargetRPM(float rpm) {
        _targetRPM = constrain(rpm, -MAX_RPM, MAX_RPM);
    }

    float   getActualRPM()    const { return _actualRPM; }
    int32_t getEncoderCount() const { return _lastCount; }

    void resetEncoder() {
        _enc.write(0);
        _lastCount = 0;
        _accTicks  = 0;
        _accCycles = 0;
        _actualRPM = 0.f;
        velPID.reset();
    }

    PIDController velPID;

private:
    MotorDriver& _driver;
    Encoder&     _enc;
    const int    _ppr;
    int32_t _lastCount;
    float   _actualRPM;
    float   _targetRPM;
    int32_t _accTicks;   // tick accumulator for the current window
    int     _accCycles;  // 50 Hz cycles elapsed in the current window
};
