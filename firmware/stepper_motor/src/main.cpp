#include <Arduino.h>
#include <AccelStepper.h>

// =============================================================================
//  WIRING — TB6600 in Common Cathode mode
//    ESP32 GPIO 26  →  TB6600 PUL+
//    ESP32 GPIO 27  →  TB6600 DIR+
//    ESP32 GND      →  TB6600 PUL- (common) & DIR- (common)
// =============================================================================
#define PIN_STEP 26
#define PIN_DIR  27

// =============================================================================
//  PHYSICAL DIMENSIONS
//
//  Current assumption: 1/4 microstep → 800 steps/rev → 100 steps/mm
//  Physical rail: ~145 mm usable travel
//
//  All distances are derived from mm so they are easy to read and adjust.
//  Do not edit the step counts directly — change the mm values only.
//
//    RAIL_MM        – real usable rail length
//    MARGIN_MM      – buffer kept from each hard stop (no limit switches yet)
//    STROKE_MM      – commanded test stroke, must be < (RAIL_MM - MARGIN_MM)
// =============================================================================
// !! HARDWARE: set TB6600 DIP switches to 1/16 microstep before running:
//    SW4=ON  SW5=ON  SW6=OFF  →  3200 steps/rev
//    Verify mechanically that 1 motor revolution = exactly 8 mm of travel.
//    If start/end still buzzes after flashing, raise ACCELERATION to 3200
//    then 4000 — do NOT lower it (longer ramp = more time in resonance band).
//    AccelStepper on ESP32 is reliable up to ~4800 sps; above that switch to
//    FastAccelStepper (hardware-timer based, drop-in replacement).
constexpr float STEPS_PER_MM = 400.0f;   // 1/16 step: 3200 steps/rev ÷ 8 mm lead

constexpr float RAIL_MM   = 145.0f;
constexpr float MARGIN_MM =  15.0f;      // 15 mm from each end — no limit switches yet
constexpr float STROKE_MM = 100.0f;      // 100 mm stroke, well inside the rail

// Derived — do not edit
constexpr long SOFT_LIMIT_STEPS = (long)((RAIL_MM - MARGIN_MM) * STEPS_PER_MM);  // 52000 = 130 mm
constexpr long TEST_STEPS       = (long)(STROKE_MM * STEPS_PER_MM);              // 40000 = 100 mm

constexpr unsigned long PAUSE_MS = 6000UL;

// =============================================================================
//  MOTION PROFILE
//
//  Vibration at start/end is low-speed resonance.  At 1/16 microstep each step
//  impulse is 4× smaller AND the resonance band shifts higher, so the motor is
//  far less prone to buzzing in the first place.  ACCELERATION = 2400 blasts
//  through any remaining resonance band in ~0.4 s.
//  Do NOT lower acceleration — longer ramp = more time in the resonance band.
// =============================================================================
constexpr float MAX_SPEED_SPS = 3200.0f;  // 8 mm/s
constexpr float ACCELERATION  = 2400.0f;  // 6 mm/s²

// =============================================================================
//  STATE MACHINE
// =============================================================================
enum class State { EXTENDING, PAUSING, RETRACTING };

AccelStepper stepper(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);

static State         state      = State::EXTENDING;
static unsigned long pauseStart = 0;
static bool          cmdIssued  = false;

static void moveSafe(long target) {
    stepper.moveTo(constrain(target, 0L, SOFT_LIMIT_STEPS));
}

// =============================================================================
//  SETUP
// =============================================================================
void setup() {
    Serial.begin(115200);
    while (!Serial) { delay(10); }

    Serial.println();
    Serial.println("=== Linear Actuator ===");
    Serial.printf("Rail=%.0f mm  |  Margin=%.0f mm  |  Stroke=%.0f mm\n",
                  RAIL_MM, MARGIN_MM, STROKE_MM);
    Serial.printf("Soft limit=%ld steps (%.0f mm)  |  Test=%ld steps (%.0f mm)\n",
                  SOFT_LIMIT_STEPS, SOFT_LIMIT_STEPS / STEPS_PER_MM,
                  TEST_STEPS,       TEST_STEPS       / STEPS_PER_MM);
    Serial.printf("V_max=%.0f sps (%.1f mm/s)  |  A=%.0f sps² (%.1f mm/s²)\n",
                  MAX_SPEED_SPS, MAX_SPEED_SPS / STEPS_PER_MM,
                  ACCELERATION,  ACCELERATION  / STEPS_PER_MM);
    Serial.println("-----------------------");

    stepper.setMaxSpeed(MAX_SPEED_SPS);
    stepper.setAcceleration(ACCELERATION);
    stepper.setCurrentPosition(0);

    Serial.println("Extending...");
    moveSafe(TEST_STEPS);
    cmdIssued = true;
}

// =============================================================================
//  LOOP
// =============================================================================
void loop() {
    stepper.run();  // must be first, every iteration — no blocking code here

    switch (state) {

        case State::EXTENDING:
            if (!cmdIssued) {
                Serial.println("Extending...");
                moveSafe(TEST_STEPS);
                cmdIssued = true;
            }
            if (stepper.distanceToGo() == 0) {
                Serial.printf("Reached end — pausing %lu ms\n", PAUSE_MS);
                pauseStart = millis();
                state      = State::PAUSING;
                cmdIssued  = false;
            }
            break;

        case State::PAUSING:
            if (millis() - pauseStart >= PAUSE_MS) {
                Serial.println("Retracting...");
                moveSafe(0);
                state     = State::RETRACTING;
                cmdIssued = true;
            }
            break;

        case State::RETRACTING:
            if (stepper.distanceToGo() == 0) {
                Serial.println("Reached home — next cycle");
                Serial.println();
                state     = State::EXTENDING;
                cmdIssued = false;
            }
            break;
    }
}
