#pragma once

// =============================================================================
// LiftControl.h — non-blocking BTS7960 scissor-lift driver.
//
// The actuator has no position encoder, so position is estimated open-loop
// from commanded run time at ACTUATOR_EXTEND_SPEED_MM_S / _RETRACT_ (the two
// differ because the load fights extension but assists retraction). There is
// deliberately no top limit switch — full-range (min retracted -> max
// extended) timing was bench-verified directly on the assembled scissor lift
// under load. The bottom switch
// stays: it's the only re-homing reference in the system, and every
// "LIFT 0" retracts until it fires, which bounds the drift that would
// otherwise accumulate over a long mission with many moves that don't start
// from 0 (e.g. shelf 200 -> home 0 -> drop-off 120 -> home 0 -> ...).
//
// Wire protocol (see docs/HANDOFF_zahra_firmware.md):
//   moveToMm(mm)  -> eventually emits "EVT LIFT DONE"
//   stop()        -> immediate halt, no event (matches the STOP command's contract)
// =============================================================================

#include <Arduino.h>
#include "Config.h"

class LiftControl {
public:
    void begin() {
        pinMode(LIFT_RPWM, OUTPUT);
        pinMode(LIFT_LPWM, OUTPUT);
        pinMode(LIFT_REN,  OUTPUT);
        pinMode(LIFT_LEN,  OUTPUT);
        digitalWrite(LIFT_REN, HIGH);
        digitalWrite(LIFT_LEN, HIGH);
        pinMode(LIFT_BOTTOM, INPUT_PULLUP);
        stopMotor();

        // Re-home at boot so currentPositionMm_ starts accurate instead of assumed.
        moveToMm(0.0f);
    }

    // Non-blocking — call once per loop() pass.
    void update() {
        if (state_ == IDLE) return;

        uint32_t now = millis();
        bool pastBlindWindow = (now - moveStartMs_) > SWITCH_BLIND_MS;

        if (state_ == HOMING) {
            if (pastBlindWindow) {
                if (digitalRead(LIFT_BOTTOM) == HIGH) {
                    // Require the HIGH read to hold for SWITCH_DEBOUNCE_MS before
                    // trusting it — BTS7960 switching noise can spike this pin
                    // for a single read well after the startup blind window, which
                    // was firing "home reached" seconds into a real ~99s retract.
                    if (switchHighSinceMs_ == 0) switchHighSinceMs_ = now;
                    if (now - switchHighSinceMs_ >= SWITCH_DEBOUNCE_MS) {
                        stopMotor();
                        currentPositionMm_ = 0.0f;
                        Serial.println("EVT LIFT DONE");
                    }
                } else {
                    switchHighSinceMs_ = 0;
                }
            }
            return;
        }

        // EXTENDING / RETRACTING: purely timed, no switch to check.
        if (now - moveStartMs_ >= durationMs_) {
            stopMotor();
            currentPositionMm_ = targetMm_;
            Serial.println("EVT LIFT DONE");
        }
    }

    // Absolute move. Targets at/near 0 go HOME (retract until the bottom switch
    // fires — exact) instead of a timed guess, since that's also the recalibration
    // point that keeps open-loop drift bounded.
    void moveToMm(float mm) {
        float target = constrain(mm, 0.0f, LIFT_MAX_TRAVEL_MM);
        targetMm_    = target;
        moveStartMs_ = millis();

        if (target <= HOME_EPSILON_MM) {
            analogWrite(LIFT_RPWM, 0);
            analogWrite(LIFT_LPWM, 255);
            state_ = HOMING;
            switchHighSinceMs_ = 0;   // fresh debounce window for this homing run
            return;
        }

        float delta = target - currentPositionMm_;
        float speed = (delta > 0.0f) ? ACTUATOR_EXTEND_SPEED_MM_S : ACTUATOR_RETRACT_SPEED_MM_S;
        durationMs_ = (uint32_t)((fabsf(delta) / speed) * 1000.0f);

        if (durationMs_ == 0) {
            // Already at the requested height — nothing to move.
            state_ = IDLE;
            Serial.println("EVT LIFT DONE");
            return;
        }

        if (delta > 0.0f) {
            analogWrite(LIFT_LPWM, 0);
            analogWrite(LIFT_RPWM, 255);
            state_ = EXTENDING;
        } else {
            analogWrite(LIFT_RPWM, 0);
            analogWrite(LIFT_LPWM, 255);
            state_ = RETRACTING;
        }
    }

    // Immediate halt — no completion event; matches the STOP command's contract.
    void stop() {
        stopMotor();
    }

private:
    enum State { IDLE, EXTENDING, RETRACTING, HOMING };

    void stopMotor() {
        analogWrite(LIFT_RPWM, 0);
        analogWrite(LIFT_LPWM, 0);
        state_ = IDLE;
    }

    // Ignore the bottom-switch read for a short window after starting a homing
    // move — the BTS7960 switching on can spike a pin momentarily. millis()-based,
    // not a delay(), so it never blocks the serial reader or a STOP.
    static constexpr uint32_t SWITCH_BLIND_MS    = 200;
    // After the blind window, still require the HIGH read to hold continuously
    // for this long before trusting it as a real switch trigger — motor driver
    // noise can spike the pin for a single read at any point during the move,
    // not just right at startup.
    static constexpr uint32_t SWITCH_DEBOUNCE_MS = 25;
    static constexpr float    HOME_EPSILON_MM    = 0.5f;

    State    state_              = IDLE;
    float    currentPositionMm_  = 0.0f;
    float    targetMm_           = 0.0f;
    uint32_t moveStartMs_        = 0;
    uint32_t durationMs_         = 0;
    uint32_t switchHighSinceMs_  = 0;   // 0 = not currently reading HIGH
};
