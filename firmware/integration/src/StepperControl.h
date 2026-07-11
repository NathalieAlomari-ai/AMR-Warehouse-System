#pragma once

// =============================================================================
// StepperControl.h — non-blocking TB6600 stepper driver for the suction-cup
// carriage (extend toward the shelf/drop-off, retract toward the robot body).
//
// Ported from the `stepper_motor_test` branch (firmware/stepper_motor/src/main.cpp,
// commit 4167a67), proven standalone on an ESP32. That sketch drove a free-running
// ping-pong demo (extend -> grip -> retract -> release -> repeat); here the motion
// is split out from the gripper (see PumpControl.h) and driven by explicit
// commands instead, matching the wire protocol in docs/HANDOFF_zahra_firmware.md
// and coordinator_node.py's granular STEP EXT / STEP RET steps.
//
// Like the lift, there's no absolute position encoder — but unlike the lift,
// motion is never timed. Both EXTEND and RETRACT always drive toward a limit
// switch (STEPPER_MAX / STEPPER_HOME) rather than a computed distance, so
// there's no open-loop drift to bound: every move is self-correcting.
//
// Wire protocol (see docs/HANDOFF_zahra_firmware.md):
//   extend()  -> eventually emits "EVT STEP DONE"
//   retract() -> eventually emits "EVT STEP DONE"
//   stop()    -> immediate halt, no event (matches the STOP command's contract)
// =============================================================================

#include <Arduino.h>
#include <AccelStepper.h>
#include "Config.h"

class StepperControl {
public:
    void begin() {
        pinMode(STEPPER_HOME_PIN, INPUT_PULLUP);
        pinMode(STEPPER_MAX_PIN,  INPUT_PULLUP);

        // Invert DIR so that positive steps = extend (away from the robot body),
        // matching the proven test sketch's convention.
        stepper_.setPinsInverted(true, false, false);
        stepper_.setMaxSpeed(STEPPER_HOMING_SPEED_SPS);
        stepper_.setAcceleration(STEPPER_ACCELERATION);
        stepper_.setCurrentPosition(0);

        // Re-home at boot, same reasoning as LiftControl: start with an accurate
        // zero instead of an assumed one.
        moveStartMs_       = millis();
        switchHighSinceMs_ = 0;
        stepper_.moveTo(-STEPPER_TRAVEL_STEPS);
        state_ = HOMING;
    }

    // Non-blocking — call once per loop() pass. stepper.run() must be called
    // every pass regardless of state so queued step pulses actually go out.
    void update() {
        stepper_.run();
        if (state_ == IDLE) return;

        if (state_ == HOMING) {
            if (limitTriggered(STEPPER_HOME_PIN)) {
                stepper_.stop();
                stepper_.setCurrentPosition(0);
                stepper_.moveTo(STEPPER_UNPRESS_STEPS);
                state_ = HOMING_BACKOFF;
            }
            return;
        }

        if (state_ == HOMING_BACKOFF) {
            if (stepper_.distanceToGo() == 0) {
                stepper_.setCurrentPosition(0);
                stepper_.setMaxSpeed(STEPPER_MAX_SPEED_SPS);
                state_ = IDLE;
                Serial.println("EVT STEP DONE");
            }
            return;
        }

        if (state_ == EXTENDING) {
            if (limitTriggered(STEPPER_MAX_PIN)) {
                stepper_.stop();
                state_ = IDLE;
                Serial.println("EVT STEP DONE");
            }
            return;
        }

        // RETRACTING
        if (limitTriggered(STEPPER_HOME_PIN)) {
            stepper_.stop();
            stepper_.setCurrentPosition(0);
            state_ = IDLE;
            Serial.println("EVT STEP DONE");
        }
    }

    // Ignored if a move is already in progress — the wire protocol only ever
    // has one outstanding STEP command at a time (the coordinator blocks on
    // "EVT STEP DONE" before sending the next one).
    void extend() {
        if (state_ != IDLE) return;
        moveStartMs_       = millis();
        switchHighSinceMs_ = 0;
        stepper_.moveTo(STEPPER_TRAVEL_STEPS);
        state_ = EXTENDING;
    }

    void retract() {
        if (state_ != IDLE) return;
        moveStartMs_       = millis();
        switchHighSinceMs_ = 0;
        stepper_.moveTo(-STEPPER_TRAVEL_STEPS);
        state_ = RETRACTING;
    }

    // Immediate halt — no completion event; matches the STOP command's contract.
    void stop() {
        stepper_.stop();
        state_ = IDLE;
    }

private:
    enum State { IDLE, HOMING, HOMING_BACKOFF, EXTENDING, RETRACTING };

    // Same shape as LiftControl's homing debounce: ignore the switch for
    // STEPPER_SWITCH_BLIND_MS after a move starts (driver-on noise spike),
    // then require the read to hold HIGH for STEPPER_SWITCH_DEBOUNCE_MS
    // before trusting it. No delay() anywhere — a real delay() here would
    // stall the serial reader and block STOP mid-move.
    bool limitTriggered(int pin) {
        if (millis() - moveStartMs_ <= STEPPER_SWITCH_BLIND_MS) return false;

        if (digitalRead(pin) == HIGH) {
            if (switchHighSinceMs_ == 0) switchHighSinceMs_ = millis();
            return (millis() - switchHighSinceMs_ >= STEPPER_SWITCH_DEBOUNCE_MS);
        }
        switchHighSinceMs_ = 0;
        return false;
    }

    AccelStepper stepper_{AccelStepper::DRIVER, STEPPER_STEP_PIN, STEPPER_DIR_PIN};

    State    state_              = IDLE;
    uint32_t moveStartMs_        = 0;
    uint32_t switchHighSinceMs_  = 0;   // 0 = not currently reading HIGH
};
