#pragma once
#include <Arduino.h>
#include <math.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include "Config.h"
#include "MotorController.h"
#include "PIDController.h"

// =============================================================================
// DriveSystem — cascade PID orchestrator for a differential-drive AMR.
//
// CASCADE ARCHITECTURE (tune from innermost outward):
//
//   Layer 1 — VelocityPID (50 Hz, inside MotorController):
//     Input : target RPM   Output: PWM duty cycle (0–255)
//     Tune this first in isolation before enabling outer layers.
//
//   Layer 2 — PositionPID (20 Hz, this class):
//     Input : target distance (m)   Output: base RPM command to both wheels
//     The output feeds into VelocityPID as the RPM setpoint.
//     Tune with SyncPID and HeadingPID disabled (set their Kp = 0 temporarily).
//
//   Layer 3 — SyncPID (20 Hz, this class):
//     Input : left encoder count − right encoder count (should be 0)
//     Output: ±RPM correction added/subtracted to left/right setpoints.
//     Corrects mechanical asymmetry during straight travel.
//     Tune after PositionPID is stable. Start with very small Kp (0.1–0.3).
//
//   Layer 4 — HeadingPID (20 Hz, this class):
//     Input : heading error in degrees   Output: ±RPM spin correction
//     During straight travel: keeps heading locked (suppresses yaw drift).
//     During ROTATE: drives the in-place spin to a new heading.
//     Tune last. Disable during MOVE_FORWARD tuning by setting its Kp = 0.
//
// SIGN CONVENTIONS (verify with your physical robot):
//   Positive RPM = forward wheel rotation = robot moves forward.
//   Increasing BNO055 heading = clockwise turn (viewed from above).
//   Positive headCorr → left wheel faster → robot turns clockwise. ✓
//   Positive syncCorr → left wheel faster → catches up to right.   ✓
//   If behaviour is inverted, negate the relevant PID Kp.
//
// BNO055 MOUNTING:
//   Mount flat, connector toward rear. If heading drifts or rotates opposite
//   to expectation, check Adafruit_BNO055::setAxisRemap() in begin().
// =============================================================================

class DriveSystem {
public:
    DriveSystem(MotorController& left, MotorController& right)
        : _left(left), _right(right),
          _bno(55, 0x29, &Wire),
          _rotating(false),
          _targetDistance(0.f),
          _targetHeading(0.f),
          // Position PID: output is base RPM for both wheels.
          // Tune Kp until robot reaches distance smoothly. Add Kd to reduce overshoot.
          posPID(/*kp*/1.2f, /*ki*/0.05f, /*kd*/0.15f,
                 /*outMin*/-MAX_RPM, /*outMax*/MAX_RPM, /*iClamp*/20.f),
          // Sync PID: keep (leftCount − rightCount) near 0.
          // Small Kp only — strong sync fights VelocityPID.
          syncPID(/*kp*/0.25f, /*ki*/0.01f, /*kd*/0.0f,
                  /*outMin*/-15.f, /*outMax*/15.f, /*iClamp*/8.f),
          // Heading PID: output is spin RPM applied differentially.
          // Tune Kp for crisp rotation, Kd to suppress overshoot at heading lock.
          headingPID(/*kp*/1.5f, /*ki*/0.02f, /*kd*/0.25f,
                     /*outMin*/-MAX_RPM * 0.5f, /*outMax*/MAX_RPM * 0.5f, /*iClamp*/15.f) {}

    // Returns false if BNO055 is not found — halt in setup() if this fails.
    bool begin() {
        _left.begin();
        _right.begin();
        if (!_bno.begin()) return false;
        _bno.setExtCrystalUse(true);
        delay(100);
        _targetHeading = getHeadingDeg();  // lock current orientation at boot
        return true;
    }

    // Outer control loop — call at 20 Hz. Inner VelocityPID runs at 50 Hz
    // inside MotorController::update(); this drives the RPM setpoints it follows.
    void updateOuter(float dt) {
        const long  lCount = _left.getEncoderCount();
        const long  rCount = _right.getEncoderCount();
        const float lDist  = (float)lCount / COUNTS_PER_METER;
        const float rDist  = (float)rCount / COUNTS_PER_METER;
        const float avgDist = (lDist + rDist) * 0.5f;

        // Layer 2: Position → base RPM for both wheels
        const float baseRPM = posPID.compute(_targetDistance, avgDist, dt);

        // Layer 3: Sync — disabled during rotation (counts diverge intentionally)
        float syncCorr = 0.f;
        if (!_rotating) {
            // Positive syncCorr → left is lagging → speed up left, slow right
            syncCorr = syncPID.compute(0.f, (float)(lCount - rCount), dt);
        }

        // Layer 4: Heading correction
        // hErr > 0 → need to turn CW → positive headCorr → left faster, right slower
        const float hErr     = _wrapAngle(_targetHeading - getHeadingDeg());
        const float headCorr = headingPID.compute(hErr, 0.f, dt);

        _left.setTargetRPM( baseRPM + headCorr + syncCorr);
        _right.setTargetRPM(baseRPM - headCorr - syncCorr);
    }

    // Command a straight-line travel to an absolute distance from the last resetOdometry().
    void setTargetDistance(float meters) {
        _targetDistance = meters;
        _rotating       = false;
        posPID.reset();
        syncPID.reset();
    }

    // Command an in-place rotation to an absolute heading (degrees, 0–360).
    // Target distance is frozen at current average to prevent forward/backward drift.
    void setTargetHeading(float degrees) {
        _targetDistance = getAverageDistance();  // hold position while rotating
        _targetHeading  = degrees;
        _rotating       = true;
        headingPID.reset();
        posPID.reset();
        syncPID.reset();
    }

    void stop() {
        _left.setTargetRPM(0.f);
        _right.setTargetRPM(0.f);
        posPID.reset();
        syncPID.reset();
        headingPID.reset();
        _rotating = false;
    }

    void resetOdometry() {
        _left.resetEncoder();
        _right.resetEncoder();
        _targetDistance = 0.f;
        posPID.reset();
        syncPID.reset();
    }

    bool isAtDistance(float toleranceM = 0.01f) const {
        return fabsf(_targetDistance - getAverageDistance()) < toleranceM;
    }

    bool isAtHeading(float toleranceDeg = 2.0f) {
        return fabsf(_wrapAngle(_targetHeading - getHeadingDeg())) < toleranceDeg;
    }

    float getHeadingDeg() {
        sensors_event_t ev;
        _bno.getEvent(&ev);
        return (float)ev.orientation.x;
    }

    float getAverageDistance() const {
        return (float)(_left.getEncoderCount() + _right.getEncoderCount())
               * 0.5f / COUNTS_PER_METER;
    }

    PIDController posPID;
    PIDController syncPID;
    PIDController headingPID;

private:
    MotorController& _left;
    MotorController& _right;
    Adafruit_BNO055  _bno;
    bool  _rotating;
    float _targetDistance;
    float _targetHeading;

    static float _wrapAngle(float a) {
        while (a >  180.f) a -= 360.f;
        while (a < -180.f) a += 360.f;
        return a;
    }
};
