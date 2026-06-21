#pragma once
#include <Arduino.h>
#include <math.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include "Config.h"
#include "MotorController.h"

// DriveSystem — IMU + odometry wrapper for a differential-drive robot.
// Motor control is open-loop; use setTargetRPM() on each MotorController directly.

class DriveSystem {
public:
    DriveSystem(MotorController& left, MotorController& right)
        : _left(left), _right(right),
          _bno(55, 0x29, &Wire) {}

    // Returns false if BNO055 is not found — halt in setup() if this fails.
    bool begin() {
        _left.begin();
        _right.begin();
        if (!_bno.begin()) return false;
        _bno.setExtCrystalUse(true);
        delay(100);
        return true;
    }

    void stop() {
        _left.setTargetRPM(0.f);
        _right.setTargetRPM(0.f);
    }

    void resetOdometry() {
        _left.resetEncoder();
        _right.resetEncoder();
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

private:
    MotorController& _left;
    MotorController& _right;
    Adafruit_BNO055  _bno;
};
