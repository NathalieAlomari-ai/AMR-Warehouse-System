#include <Arduino.h>

// BTS7960 driver pins
const int LPWM_PIN = 18; // Extend
const int RPWM_PIN = 19; // Retract
const int L_EN_PIN = 21;
const int R_EN_PIN = 22;

// Limit switches, wired Normally Closed (NC) to GND: LOW = clear, HIGH = hit / wire cut
const int BOTTOM_SWITCH_PIN = 32; // 0 mm home
const int TOP_SWITCH_PIN = 33;    // 250 mm kinematic failsafe

const int FULL_SPEED_PWM = 255;
const float ACTUATOR_SPEED_MM_S = 5.0f;

enum MotionState { STOPPED, EXTENDING, RETRACTING };

MotionState state = STOPPED;
bool timerActive = false;
unsigned long moveStartMs = 0;
unsigned long targetDurationMs = 0;
const char *targetReachedMsg = "";

void stopMotor() {
  analogWrite(LPWM_PIN, 0);
  analogWrite(RPWM_PIN, 0);
  state = STOPPED;
  timerActive = false;
}

void extendFor(unsigned long durationMs, const char *reachedMsg) {
  analogWrite(RPWM_PIN, 0);
  analogWrite(LPWM_PIN, FULL_SPEED_PWM);
  state = EXTENDING;
  moveStartMs = millis();
  targetDurationMs = durationMs;
  targetReachedMsg = reachedMsg;
  timerActive = true;
}

void retractIndefinite() {
  analogWrite(LPWM_PIN, 0);
  analogWrite(RPWM_PIN, FULL_SPEED_PWM);
  state = RETRACTING;
  timerActive = false;
}

void handleCommand(char cmd) {
  switch (cmd) {
    case '1': {
      unsigned long ms = (unsigned long)((100.0f / ACTUATOR_SPEED_MM_S) * 1000.0f);
      Serial.println("CMD 1: Safe Scenario - Extending to 100mm stroke (20000 ms)");
      extendFor(ms, "Safe Target Reached");
      break;
    }
    case '2': {
      unsigned long ms = (unsigned long)((350.0f / ACTUATOR_SPEED_MM_S) * 1000.0f);
      Serial.println("CMD 2: Emergency Scenario - Extending to 350mm stroke (70000 ms) - hardware failsafe expected at 250mm");
      extendFor(ms, "WARNING: 350mm timer elapsed without failsafe trigger - check top limit switch wiring");
      break;
    }
    case '0':
      Serial.println("CMD 0: Go Home - Retracting until Bottom Switch triggers");
      retractIndefinite();
      break;
    case 'S':
    case 's':
      Serial.println("MANUAL STOP: PWM cut, all timers cancelled");
      stopMotor();
      break;
    default:
      break;
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(LPWM_PIN, OUTPUT);
  pinMode(RPWM_PIN, OUTPUT);
  pinMode(L_EN_PIN, OUTPUT);
  pinMode(R_EN_PIN, OUTPUT);
  digitalWrite(L_EN_PIN, HIGH);
  digitalWrite(R_EN_PIN, HIGH);

  pinMode(BOTTOM_SWITCH_PIN, INPUT_PULLUP);
  pinMode(TOP_SWITCH_PIN, INPUT_PULLUP);

  stopMotor();

  Serial.println("Linear Actuator Test Sketch Ready");
  Serial.println("Commands: 1=Safe(100mm) 2=Emergency(350mm) 0=Home S=Stop");
}

void loop() {
  // Hardware failsafe override - checked first, every cycle, before anything else
  if (state == EXTENDING && digitalRead(TOP_SWITCH_PIN) == HIGH) {
    analogWrite(LPWM_PIN, 0);
    analogWrite(RPWM_PIN, 0);
    state = STOPPED;
    timerActive = false;
    Serial.println("EMERGENCY: TOP LIMIT (250mm) HIT. POWER CUT.");
  }

  if (state == RETRACTING && digitalRead(BOTTOM_SWITCH_PIN) == HIGH) {
    analogWrite(LPWM_PIN, 0);
    analogWrite(RPWM_PIN, 0);
    state = STOPPED;
    timerActive = false;
    Serial.println("HOME: BOTTOM LIMIT (0mm) HIT.");
  }

  if (timerActive && state == EXTENDING && (millis() - moveStartMs >= targetDurationMs)) {
    stopMotor();
    Serial.println(targetReachedMsg);
  }

  if (Serial.available() > 0) {
    char cmd = (char)Serial.read();
    handleCommand(cmd);
  }
}
