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
//  LIMIT SWITCHES — NC (Normally Closed) wired to GND, INPUT_PULLUP
//    Normal state : pin LOW  (switch closed, pulling to GND)
//    Triggered    : pin HIGH (switch opened OR wire broken — failsafe)
//    HOME_PIN     : bottom of rail (GPIO 32)
//    MAX_PIN      : top of rail    (GPIO 33)
// =============================================================================
#define HOME_PIN 32
#define MAX_PIN  33

// =============================================================================
//  PHYSICAL DIMENSIONS
//
//  1/16 microstep → 3200 steps/rev → 400 steps/mm (8 mm lead screw)
// =============================================================================
// !! HARDWARE: set TB6600 DIP switches to 1/16 microstep before running:
//    SW4=ON  SW5=ON  SW6=OFF  →  3200 steps/rev
constexpr float STEPS_PER_MM = 400.0f;

// Large target used as "move until limit switch fires"
constexpr long TRAVEL_STEPS = 1000000L;

// =============================================================================
//  MOTION PROFILE
// =============================================================================
constexpr float MAX_SPEED_SPS    = 3200.0f;  // 8 mm/s  — normal operation
constexpr float HOMING_SPEED_SPS =  400.0f;  // 1 mm/s  — slow creep during homing
constexpr float ACCELERATION     = 2400.0f;  // 6 mm/s²

constexpr long UN_PRESS_STEPS = 200L;  // back off after home switch contact

// =============================================================================
//  STATE MACHINE
// =============================================================================
enum class State { HOMING, EXTENDING, RETRACTING };

AccelStepper stepper(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);

static State state            = State::HOMING;
static bool  cmdIssued        = false;
static bool  homingUnpressing = false;  // false=searching, true=backing off

// =============================================================================
//  SETUP
// =============================================================================
void setup() {
    Serial.begin(115200);
    while (!Serial) { delay(10); }

    pinMode(HOME_PIN, INPUT_PULLUP);
    pinMode(MAX_PIN,  INPUT_PULLUP);

    // Invert DIR so that positive steps = UP (away from motor)
    stepper.setPinsInverted(true, false, false);  // invert DIR so +steps = UP

    stepper.setMaxSpeed(HOMING_SPEED_SPS);
    stepper.setAcceleration(ACCELERATION);
    stepper.setCurrentPosition(0);

    Serial.println();
    Serial.println("=== Linear Actuator — Ping-Pong Mode ===");
    Serial.printf("V_max=%.0f sps (%.1f mm/s)  |  A=%.0f sps² (%.1f mm/s²)\n",
                  MAX_SPEED_SPS, MAX_SPEED_SPS / STEPS_PER_MM,
                  ACCELERATION,  ACCELERATION  / STEPS_PER_MM);
    Serial.println("-----------------------------------------");

    // Begin homing: creep down until HOME_PIN fires
    stepper.moveTo(-TRAVEL_STEPS);
    Serial.println("Homing...");
}

// =============================================================================
//  LOOP
// =============================================================================
void loop() {
    stepper.run();  // must be first, every iteration — no blocking code here

    switch (state) {

        case State::HOMING:
            if (!homingUnpressing) {
                // Phase 1: creeping down, waiting for home switch
                if (digitalRead(HOME_PIN) == HIGH) {
                    stepper.stop();
                    stepper.setCurrentPosition(0);
                    stepper.moveTo(UN_PRESS_STEPS);
                    homingUnpressing = true;
                    Serial.println("Home switch triggered — backing off...");
                } else if (stepper.distanceToGo() == 0) {
                    Serial.println("ERROR: Home switch not found — halted. Check wiring.");
                }
            } else {
                // Phase 2: back-off move complete → set true home
                if (stepper.distanceToGo() == 0) {
                    stepper.setCurrentPosition(0);
                    stepper.setMaxSpeed(MAX_SPEED_SPS);
                    state     = State::EXTENDING;
                    cmdIssued = false;
                    Serial.println("Homing complete — starting ping-pong.");
                    Serial.println();
                }
            }
            break;

        case State::EXTENDING:
            if (!cmdIssued) {
                Serial.println("Extending...");
                stepper.moveTo(TRAVEL_STEPS);
                cmdIssued = true;
            }
            if (digitalRead(MAX_PIN) == HIGH) {
                stepper.stop();
                Serial.println("Max reached.");
                state     = State::RETRACTING;
                cmdIssued = false;
            }
            break;

        case State::RETRACTING:
            if (!cmdIssued) {
                Serial.println("Retracting...");
                stepper.moveTo(-TRAVEL_STEPS);
                cmdIssued = true;
            }
            if (digitalRead(HOME_PIN) == HIGH) {
                stepper.stop();
                stepper.setCurrentPosition(0);
                Serial.println("Home reached.");
                state     = State::EXTENDING;
                cmdIssued = false;
            }
            break;
    }
}
