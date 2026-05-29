// =============================================================================
// line_follower_pid.ino
// 4-motor PID line follower — tank drive (2 left wheels, 2 right wheels)
// Hardware: Arduino Uno/Nano, 2× L298N drivers, 3× IR sensors
// Power:    11.1V battery → L298N 12V inputs; L298N 5V output → Arduino 5V pin
//
// QUICK-START CHECKLIST:
//   1. Bench-test first: set BASE_SPEED = 0, open Serial Monitor, cover sensors
//      to verify the truth table output before connecting motors.
//   2. Motor direction test: call setMotors(80, 80) in setup(); both sides must
//      spin forward. If one side reverses, swap FWD/REV in code for that side.
//   3. Tune PID in order: Kp first, then Kd, lastly Ki (see comments below).
// =============================================================================

// =============================================================================
// SECTION 1 — TUNABLE PARAMETERS
// All user-adjustable knobs live here. Change nothing else for normal tuning.
// =============================================================================

// --- PID Gains ---
// Tune in order: set Ki=Kd=0, raise Kp until oscillation, back off 20%.
// Then raise Kd until oscillation damps. Only add Ki if robot drifts on straights.
const float Kp = 25.0;    // Proportional — higher = faster reaction, too high = oscillation
const float Ki = 0.0;     // Integral     — corrects steady drift; start at 0, add in 0.001 steps
const float Kd = 15.0;    // Derivative   — dampens oscillation; typically 0.5–0.8 × Kp

// --- Motor Speeds ---
const int BASE_SPEED = 120;   // PWM at centre of track (0–255); lower = more stable on tight turns
const int MAX_SPEED  = 220;   // Upper PWM clamp; keeps headroom below 255 for proportional control
const int MIN_SPEED  = 0;     // Lower PWM clamp; keep ≥ 0 for forward-only tracking

// --- Integral Anti-Windup ---
// Caps the accumulated integral so Ki never dominates the PID output.
const float INTEGRAL_CLAMP = 50.0;

// --- Fail-Safe Timing ---
const unsigned long STOP_BEFORE_SEARCH_MS = 200;   // ms to pause before starting search rotation
const unsigned long SEARCH_TIMEOUT_MS     = 2000;  // ms to rotate before giving up and stopping

// --- Search Speed ---
const int SEARCH_SPEED = 80;  // PWM for slow in-place rotation during line search

// =============================================================================
// SECTION 2 — PIN DEFINITIONS
// Match these to your exact wiring. Do not change unless rewired.
// =============================================================================

// Left side — L298N Driver 1 (controls both left wheels via bridged IN1+IN3, IN2+IN4)
const int PIN_LEFT_EN  = 5;   // PWM enable — must be a PWM-capable pin
const int PIN_LEFT_FWD = 4;   // HIGH = forward direction
const int PIN_LEFT_REV = 2;   // HIGH = reverse direction

// Right side — L298N Driver 2 (controls both right wheels via bridged IN1+IN3, IN2+IN4)
const int PIN_RIGHT_EN  = 9;  // PWM enable — must be a PWM-capable pin
const int PIN_RIGHT_FWD = 8;  // HIGH = forward direction
const int PIN_RIGHT_REV = 7;  // HIGH = reverse direction

// IR sensors — digital input on analog-labeled pins (valid on Arduino)
// Sensor logic: HIGH (1) = sees black line, LOW (0) = sees white floor
// If your module is active-LOW (many TCRT5000 breakouts), flip to !digitalRead() in readError()
const int PIN_SENSOR_LEFT   = A0;
const int PIN_SENSOR_CENTER = A1;
const int PIN_SENSOR_RIGHT  = A2;

// =============================================================================
// SECTION 3 — CONSTANTS & TYPES
// =============================================================================

// Sentinel returned by readError() when all three sensors see white (line lost)
const int ERROR_LOST = -99;

// Robot operating states for the fail-safe state machine
enum RobotState {
    FOLLOWING,  // Actively tracking the line via PID
    SEARCHING,  // Line lost — executing timed rotation to recover
    STOPPED     // Search timed out — motors off, awaiting power cycle
};

// =============================================================================
// SECTION 4 — GLOBAL STATE
// =============================================================================

RobotState robotState    = FOLLOWING;

float pidIntegral        = 0.0;
float pidLastError       = 0.0;
int   lastKnownError     = 0;   // Direction of last valid error; guides search rotation

unsigned long stateEnteredAt = 0;  // millis() timestamp of last state transition

// =============================================================================
// SECTION 5 — FUNCTION DECLARATIONS
// =============================================================================

int  readError();
void setMotors(int leftSpeed, int rightSpeed);
void handleLineLost();

// =============================================================================
// SECTION 6 — setup()
// =============================================================================

void setup() {
    // IR sensor pins — digitalRead works on analog-labeled pins with this pinMode call
    pinMode(PIN_SENSOR_LEFT,   INPUT);
    pinMode(PIN_SENSOR_CENTER, INPUT);
    pinMode(PIN_SENSOR_RIGHT,  INPUT);

    // Left motor driver pins
    pinMode(PIN_LEFT_EN,  OUTPUT);
    pinMode(PIN_LEFT_FWD, OUTPUT);
    pinMode(PIN_LEFT_REV, OUTPUT);

    // Right motor driver pins
    pinMode(PIN_RIGHT_EN,  OUTPUT);
    pinMode(PIN_RIGHT_FWD, OUTPUT);
    pinMode(PIN_RIGHT_REV, OUTPUT);

    setMotors(0, 0);  // Ensure motors are stopped before loop begins

    // Serial output for bench testing — remove in production to save loop time
    Serial.begin(9600);
    Serial.println("PID Line Follower started.");
}

// =============================================================================
// SECTION 7 — loop()
// =============================================================================

void loop() {
    int error = readError();

    // --- Fail-safe path ---
    if (error == ERROR_LOST) {
        handleLineLost();
        return;
    }

    // --- Line reacquired ---
    // Reset PID history when returning from a search to prevent integral windup
    // from accumulated stale error and a sudden large derivative spike.
    if (robotState != FOLLOWING) {
        robotState   = FOLLOWING;
        pidIntegral  = 0.0;
        pidLastError = 0.0;
        Serial.println("Line reacquired. Resuming FOLLOWING.");
    }

    lastKnownError = error;  // Save for directional search if line is lost next iteration

    // --- PID computation ---
    pidIntegral += error;
    pidIntegral  = constrain(pidIntegral, -INTEGRAL_CLAMP, INTEGRAL_CLAMP);  // anti-windup

    float derivative = error - pidLastError;
    pidLastError     = error;

    float output = (Kp * (float)error)
                 + (Ki * pidIntegral)
                 + (Kd * derivative);

    // --- Differential drive ---
    // Positive output → steer right → speed up left, slow down right
    int leftSpeed  = BASE_SPEED + (int)output;
    int rightSpeed = BASE_SPEED - (int)output;

    leftSpeed  = constrain(leftSpeed,  MIN_SPEED, MAX_SPEED);
    rightSpeed = constrain(rightSpeed, MIN_SPEED, MAX_SPEED);

    setMotors(leftSpeed, rightSpeed);
}

// =============================================================================
// SECTION 8 — readError()
//
// Reads the three IR sensors and returns a signed positional error.
//
// Sign convention (must match the setMotors() differential drive assignment):
//   Positive error → robot drifted LEFT  of line → output > 0 → steer RIGHT
//   Negative error → robot drifted RIGHT of line → output < 0 → steer LEFT
//   ERROR_LOST     → all sensors off line → trigger fail-safe
//
// Truth table — all 8 combinations of (L, C, R):
//
//   State | L  C  R | Error | Meaning
//   ------+---------+-------+--------------------------------------------
//   0b000 | 0  0  0 | LOST  | No sensor sees line → line lost
//   0b001 | 0  0  1 |  +2   | Only right sensor on → robot far left
//   0b010 | 0  1  0 |   0   | Only centre on → robot centred
//   0b011 | 0  1  1 |  +1   | Centre + right on → slight left drift
//   0b100 | 1  0  0 |  -2   | Only left sensor on → robot far right
//   0b101 | 1  0  1 |   0   | Both outers on (T-junction) → go straight
//   0b110 | 1  1  0 |  -1   | Centre + left on → slight right drift
//   0b111 | 1  1  1 |   0   | All on (wide line / intersection) → straight
// =============================================================================

int readError() {
    int L = digitalRead(PIN_SENSOR_LEFT);    // 1 = sees black tape
    int C = digitalRead(PIN_SENSOR_CENTER);
    int R = digitalRead(PIN_SENSOR_RIGHT);

    // Pack into a 3-bit integer for a readable switch statement
    int state = (L << 2) | (C << 1) | R;

    switch (state) {
        case 0b000: return ERROR_LOST;  // All white → line lost
        case 0b001: return  2;          // Far left of line
        case 0b010: return  0;          // Centred
        case 0b011: return  1;          // Slight left drift
        case 0b100: return -2;          // Far right of line
        case 0b101: return  0;          // T-junction — treat as straight
        case 0b110: return -1;          // Slight right drift
        case 0b111: return  0;          // Wide line / all sensors on — straight
        default:    return  0;          // Unreachable, but satisfies compiler
    }
}

// =============================================================================
// SECTION 9 — setMotors(int leftSpeed, int rightSpeed)
//
// Drives both motor channels.
//   Positive value = forward  (FWD pin HIGH, REV pin LOW)
//   Negative value = reverse  (FWD pin LOW,  REV pin HIGH)
//   Zero           = coast    (both direction pins LOW, EN = 0)
//
// The magnitude is passed to analogWrite on the EN pin (0–255).
// =============================================================================

void setMotors(int leftSpeed, int rightSpeed) {
    // ---- Left side ----
    if (leftSpeed > 0) {
        digitalWrite(PIN_LEFT_FWD, HIGH);
        digitalWrite(PIN_LEFT_REV, LOW);
    } else if (leftSpeed < 0) {
        digitalWrite(PIN_LEFT_FWD, LOW);
        digitalWrite(PIN_LEFT_REV, HIGH);
        leftSpeed = -leftSpeed;           // Convert to positive magnitude for analogWrite
    } else {
        digitalWrite(PIN_LEFT_FWD, LOW);
        digitalWrite(PIN_LEFT_REV, LOW);
    }
    analogWrite(PIN_LEFT_EN, constrain(leftSpeed, 0, 255));

    // ---- Right side ----
    if (rightSpeed > 0) {
        digitalWrite(PIN_RIGHT_FWD, HIGH);
        digitalWrite(PIN_RIGHT_REV, LOW);
    } else if (rightSpeed < 0) {
        digitalWrite(PIN_RIGHT_FWD, LOW);
        digitalWrite(PIN_RIGHT_REV, HIGH);
        rightSpeed = -rightSpeed;
    } else {
        digitalWrite(PIN_RIGHT_FWD, LOW);
        digitalWrite(PIN_RIGHT_REV, LOW);
    }
    analogWrite(PIN_RIGHT_EN, constrain(rightSpeed, 0, 255));
}

// =============================================================================
// SECTION 10 — handleLineLost()
//
// Three-state fail-safe machine. Called every loop() iteration while
// readError() returns ERROR_LOST.
//
// State transitions:
//   FOLLOWING  → (first call with LOST) → stop, enter SEARCHING, record time
//   SEARCHING  → [0, STOP_BEFORE_SEARCH_MS)   : stay stopped (brief pause)
//             → [STOP_BEFORE_SEARCH_MS, timeout): rotate toward lastKnownError
//             → timeout exceeded               : enter STOPPED
//   STOPPED    → motors off indefinitely (power cycle required)
//   Any state  → line found in loop()          → return to FOLLOWING
//
// Rotation direction:
//   lastKnownError > 0 → robot was left of line → rotate RIGHT (L fwd, R rev)
//   lastKnownError ≤ 0 → robot was right of line → rotate LEFT (L rev, R fwd)
// =============================================================================

void handleLineLost() {
    unsigned long now = millis();

    switch (robotState) {

        case FOLLOWING:
            // First iteration with no line — stop immediately and start timer
            setMotors(0, 0);
            robotState     = SEARCHING;
            stateEnteredAt = now;
            Serial.println("Line LOST. Entering SEARCHING state.");
            break;

        case SEARCHING: {
            unsigned long elapsed = now - stateEnteredAt;

            if (elapsed < STOP_BEFORE_SEARCH_MS) {
                // Brief pause before rotating — prevents momentum from confusing direction
                setMotors(0, 0);

            } else if (elapsed <= STOP_BEFORE_SEARCH_MS + SEARCH_TIMEOUT_MS) {
                // Active search: rotate slowly toward the direction the line was last seen
                if (lastKnownError >= 0) {
                    // Line was to the right of robot → rotate right to sweep back onto it
                    setMotors( SEARCH_SPEED, -SEARCH_SPEED);
                } else {
                    // Line was to the left of robot → rotate left
                    setMotors(-SEARCH_SPEED,  SEARCH_SPEED);
                }

            } else {
                // Search timed out — give up to avoid damage or runaway behaviour
                setMotors(0, 0);
                robotState = STOPPED;
                Serial.println("Search TIMEOUT. Entering STOPPED state. Power cycle required.");
            }
            break;
        }

        case STOPPED:
            // Full stop — do nothing until robot is power-cycled or manually reset
            setMotors(0, 0);
            break;
    }
}

// =============================================================================
// END OF FILE
//
// PHYSICAL SETUP REFERENCE:
//
// Track width:      Use 19 mm (3/4") black electrical tape.
//
// Sensor spacing:   Mount outer sensors 25–30 mm from the centre sensor
//                   (centre-to-outer, not outer-to-outer total).
//                   Rule: tape_width/2 < spacing < tape_width
//                   With 19 mm tape → spacing must be 10–19 mm minimum,
//                   25–30 mm recommended for a reliable detection buffer.
//
//   [L]----27 mm----[C]----27 mm----[R]   (top view, perpendicular to travel)
//                    |<--19 mm-->|
//                      tape width
//
// Sensor height:    8–12 mm above floor surface for TCRT5000-type sensors.
//                   Below 5 mm risks ground contact. Above 15 mm reduces contrast.
//
// IR sensor wiring (each sensor has 3 pins):
//   VCC  → Arduino 5V (sourced from L298N #1 onboard 5V regulator output)
//   GND  → Common GND rail (battery −, both L298N GNDs, Arduino GND)
//   OUT  → A0 (left), A1 (centre), A2 (right)
//
// IMPORTANT: Do NOT connect USB and the L298N 5V→Arduino 5V simultaneously.
//            Backfeeding can damage the Arduino or L298N regulator.
// =============================================================================
