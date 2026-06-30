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
//  VACUUM GRIPPER — relay module (active HIGH)
//    ESP32 GPIO 18  →  Relay 1 (Pump)
//    ESP32 GPIO 19  →  Relay 2 (Valve — solenoid, NC side routes pump→cup)
// =============================================================================
#define PIN_PUMP_RELAY  18
#define PIN_VALVE_RELAY 19

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
//  LIMIT-SWITCH DEBOUNCE
// =============================================================================
constexpr unsigned long SWITCH_BLIND_MS    = 500UL;  // ignore switches after motion starts
constexpr unsigned long SWITCH_DEBOUNCE_MS =  20UL;  // double-read confirmation window

// =============================================================================
//  STATE MACHINE
// =============================================================================
enum class State { HOMING, EXTENDING, GRIPPING, RETRACTING, RELEASING };

AccelStepper stepper(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);

static State         state            = State::HOMING;
static bool          cmdIssued        = false;
static bool          homingUnpressing = false;  // false=searching, true=backing off
static unsigned long stateEnteredMs   = 0;      // millis() when GRIPPING/RELEASING began
static bool          pumpOff          = false;  // sub-phase flag inside RELEASING
static unsigned long motionStartedMs  = 0;      // millis() when EXTENDING/RETRACTING began

// Returns true only if pin reads HIGH both now and after SWITCH_DEBOUNCE_MS.
// delay() here is safe: stepper.stop() is called immediately after a true return.
bool isLimitSwitchActive(int pin) {
    if (digitalRead(pin) != HIGH) return false;
    delay(SWITCH_DEBOUNCE_MS);
    return (digitalRead(pin) == HIGH);
}

// =============================================================================
//  SETUP
// =============================================================================
void setup() {
    Serial.begin(115200);
    while (!Serial) { delay(10); }

    pinMode(HOME_PIN, INPUT_PULLUP);
    pinMode(MAX_PIN,  INPUT_PULLUP);

    pinMode(PIN_PUMP_RELAY,  OUTPUT);
    pinMode(PIN_VALVE_RELAY, OUTPUT);
    digitalWrite(PIN_PUMP_RELAY,  LOW);
    digitalWrite(PIN_VALVE_RELAY, LOW);

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
                if (isLimitSwitchActive(HOME_PIN)) {
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
                motionStartedMs = millis();
                Serial.println("Extending...");
                stepper.moveTo(TRAVEL_STEPS);
                cmdIssued = true;
            }
            if (digitalRead(MAX_PIN) == HIGH && millis() - motionStartedMs <= SWITCH_BLIND_MS)
                Serial.printf("[DBG] MAX_PIN spike rejected — %lums into blind window\n",
                              millis() - motionStartedMs);
            if (millis() - motionStartedMs > SWITCH_BLIND_MS && isLimitSwitchActive(MAX_PIN)) {
                stepper.stop();
                Serial.println("Extended — gripping...");
                digitalWrite(PIN_VALVE_RELAY, HIGH);
                delay(200);  // allow solenoid valve to physically open
                digitalWrite(PIN_PUMP_RELAY, HIGH);
                stateEnteredMs = millis();
                state = State::GRIPPING;
            }
            break;

        case State::GRIPPING:
            if (millis() - stateEnteredMs >= 1000UL) {
                Serial.println("Grip confirmed — retracting...");
                stepper.moveTo(-TRAVEL_STEPS);
                state     = State::RETRACTING;
                cmdIssued = false;
            }
            break;

        case State::RETRACTING:
            if (!cmdIssued) {
                motionStartedMs = millis();
                Serial.println("Retracting...");
                stepper.moveTo(-TRAVEL_STEPS);
                cmdIssued = true;
            }
            if (digitalRead(HOME_PIN) == HIGH && millis() - motionStartedMs <= SWITCH_BLIND_MS)
                Serial.printf("[DBG] HOME_PIN spike rejected — %lums into blind window\n",
                              millis() - motionStartedMs);
            if (millis() - motionStartedMs > SWITCH_BLIND_MS && isLimitSwitchActive(HOME_PIN)) {
                stepper.stop();
                stepper.setCurrentPosition(0);
                Serial.println("Retracted — releasing...");
                digitalWrite(PIN_PUMP_RELAY, LOW);
                stateEnteredMs = millis();
                pumpOff = false;
                state = State::RELEASING;
            }
            break;

        case State::RELEASING:
            if (!pumpOff && millis() - stateEnteredMs >= 500UL) {
                digitalWrite(PIN_VALVE_RELAY, LOW);
                Serial.println("Released — system vented.");
                pumpOff   = true;
                state     = State::EXTENDING;
                cmdIssued = false;
            }
            break;
    }
}
