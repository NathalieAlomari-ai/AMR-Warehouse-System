#pragma once

// =============================================================================
// PumpControl.h — non-blocking vacuum gripper (pump + solenoid valve relays).
//
// Ported from the `stepper_motor_test` branch (firmware/stepper_motor/src/main.cpp,
// commit 4167a67). That sketch fired the valve/pump as one immediate step inside
// its own EXTENDING/RETRACTING states; here it's a standalone subsystem driven by
// its own commands (PUMP ON / PUMP OFF), matching coordinator_node.py's granular
// protocol — StepControl and PumpControl don't know about each other, the Jetson
// sequences them.
//
// Wire protocol (see docs/HANDOFF_zahra_firmware.md):
//   pumpOn()  -> eventually emits "EVT PUMP ON"
//   pumpOff() -> eventually emits "EVT PUMP OFF"
//   stop()    -> deliberately does nothing (see note on stop() below)
// =============================================================================

#include <Arduino.h>
#include "Config.h"

class PumpControl {
public:
    void begin() {
        pinMode(PUMP_RELAY_PIN,  OUTPUT);
        pinMode(VALVE_RELAY_PIN, OUTPUT);
        digitalWrite(PUMP_RELAY_PIN,  LOW);
        digitalWrite(VALVE_RELAY_PIN, LOW);
    }

    // Non-blocking — call once per loop() pass.
    void update() {
        if (state_ == ENGAGING) {
            if (millis() - phaseStartMs_ >= VALVE_SETTLE_MS) {
                digitalWrite(PUMP_RELAY_PIN, HIGH);
                state_ = IDLE;
                Serial.println("EVT PUMP ON");
            }
            return;
        }

        if (state_ == DISENGAGING) {
            if (millis() - phaseStartMs_ >= PUMP_VENT_SETTLE_MS) {
                digitalWrite(VALVE_RELAY_PIN, LOW);
                state_ = IDLE;
                Serial.println("EVT PUMP OFF");
            }
        }
    }

    // Opens the valve immediately, waits for it to physically seat before
    // energizing the pump (VALVE_SETTLE_MS, same value as the proven test
    // sketch's delay(200) — just non-blocking here).
    void pumpOn() {
        if (state_ != IDLE) return;
        digitalWrite(VALVE_RELAY_PIN, HIGH);
        phaseStartMs_ = millis();
        state_ = ENGAGING;
    }

    // Cuts the pump immediately, holds the valve shut for PUMP_VENT_SETTLE_MS
    // (lets suction bleed off in a controlled way) before venting.
    void pumpOff() {
        if (state_ != IDLE) return;
        digitalWrite(PUMP_RELAY_PIN, LOW);
        phaseStartMs_ = millis();
        state_ = DISENGAGING;
    }

    // Deliberately a no-op: STOP is an e-stop for *motion* (drive/lift/stepper).
    // If the gripper is mid-hold when STOP fires, cutting the pump would drop
    // whatever it's holding — releasing a grip has to be a deliberate PUMP OFF,
    // never a side effect of an emergency stop.
    void stop() {}

private:
    enum State { IDLE, ENGAGING, DISENGAGING };

    State    state_        = IDLE;
    uint32_t phaseStartMs_ = 0;
};
