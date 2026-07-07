# Firmware hand-off — port lift + stepper + pump onto the one Teensy 4.1

**To:** Zahra   **From:** Nathalie   **Branch to work on:** `feature/system-integration` (firmware in `firmware/src/`)

## What this is
The linear actuator (from `linear_acc`) and the stepper + vacuum pump (from `stepper_motor_test`)
were each tested on their **own ESP32**. We are moving both onto the **single Teensy 4.1** that
already runs the drive PID + odometry, because the whole robot must talk over **one** USB serial
line (`/dev/ttyACM0`). The ROS side is already done on my branch:

- `serial_bridge_node` is the **only** program that opens the port. It forwards any string it
  receives on `/aux/command` straight to the Teensy, and republishes any Teensy line starting
  with `EVT ` onto `/aux/status`.
- The mission coordinator sends you commands and **waits for your `EVT … DONE` reply** before
  moving on. So the firmware contract below is what makes the whole mission work.

Your job: make the Teensy understand the new commands and drive the new hardware **without ever
blocking the drive control loops**.

---

## ⚠️ The #1 landmine: pin collisions

The ESP32 sketches reused pin numbers that are **already taken on the Teensy**. If you copy the
pin numbers over literally you will kill the IMU or the wheel encoders. Here is the conflict and a
safe re-mapping. **Teensy pins already in use — do not touch:** `2–9` (motor drivers), `18/19`
(BNO055 I²C), `20–23` (encoders).

| Hardware | ESP32 pin | Conflicts with on Teensy | ➜ New Teensy pin (free) |
|---|---|---|---|
| Lift BTS7960 RPWM (extend)  | 19 | **BNO055 SCL** | **28** (PWM) |
| Lift BTS7960 LPWM (retract) | 18 | **BNO055 SDA** | **29** (PWM) |
| Lift BTS7960 R_EN           | 22 | **encoder** | **30** |
| Lift BTS7960 L_EN           | 21 | **encoder** | **31** |
| Lift bottom limit (0 mm)    | 32 | free | **34** |
| Lift top limit (failsafe)   | 33 | free | **35** |
| Stepper TB6600 STEP         | 26 | free | **24** |
| Stepper TB6600 DIR          | 27 | free | **25** |
| Pump relay                  | 18 | **BNO055 SDA** | **36** |
| Valve relay                 | 19 | **BNO055 SCL** | **37** |
| Stepper home limit          | 32 | free | **38** |
| Stepper max limit           | 33 | free | **39** |

> Please **verify 28/29 are PWM-capable in your wiring** (they are on Teensy 4.1 FlexPWM) and that
> nothing mechanical needs 5 V logic — Teensy pins are **3.3 V only, not 5 V tolerant**. TB6600 /
> relay boards usually accept 3.3 V logic; confirm yours do or add a level shifter.

Put all of these in `firmware/src/Config.h` as named constants so there is one place to change them.

---

## The rule: everything runs in `loop()`, nothing blocks

The drive PID runs inside `IntervalTimer` ISRs at 50/20 Hz. If you block `loop()`, you starve the
serial reader and the mission stalls — and worse, a `delay()` during a move means the robot can't
react to a `STOP`. So port the ESP32 code with these three edits:

1. **Delete `while (!Serial) {}`** — the Teensy runs headless; that line hangs forever with no PC
   monitor attached.
2. **Delete every `delay()`.** The stepper sketch has `delay(200)` (valve settle) and `delay(20)`
   (debounce). Replace them with `millis()` timestamps (see the `LiftControl` example below — the
   `linear_acc` sketch already does this correctly and is your template).
3. **Keep `AccelStepper`**, but call `stepper.run()` **once at the top of `loop()` every pass** —
   never from a timer/ISR. Lift and relays are just `analogWrite`/`digitalWrite` inside `update()`.

(No `ledc*` porting needed — that was ESP32 API. On Teensy use `analogWrite` and, if you want a
specific PWM frequency, `analogWriteFrequency(pin, hz)` once in `setup()`.)

---

## The wire protocol you must implement

**Host → Teensy** (one command per line, `\n` terminated — arrives via `/aux/command`):

| Command | Meaning | Emit when done |
|---|---|---|
| `LIFT <mm>`  | move lift to absolute height in mm (0 = home) | `EVT LIFT DONE` |
| `STEP EXT`   | extend suction-cup carriage to the box | `EVT STEP DONE` |
| `STEP RET`   | retract carriage back onto the robot | `EVT STEP DONE` |
| `PUMP ON`    | valve open + pump on (grip) | `EVT PUMP ON` |
| `PUMP OFF`   | pump off + valve close (release) | `EVT PUMP OFF` |
| `SERVO <deg>`| brief wheel nudge for vision centring (see note) | *(no event)* |
| `STOP`       | **immediately** halt all aux motion | *(no event)* |

**Teensy → Host** (must begin with `EVT ` so the bridge routes it to `/aux/status`; anything else
is treated as normal telemetry):

```
EVT LIFT DONE
EVT STEP DONE
EVT PUMP ON
EVT PUMP OFF
EVT FAULT <what>        ← e.g. "EVT FAULT lift top limit" — aborts the mission
```

> **`SERVO <deg>`** is optional for you right now. If the drive firmware already handles a small
> differential wheel nudge, apply it there. If not, you can ignore `SERVO` for the first bring-up —
> the mission still completes; centring just won't nudge. It does **not** need an `EVT`.

> **Do NOT change the 6-field telemetry line** (`L_RPM:… R_RPM:… Hdg:… Dist:… Lcnt:… Rcnt:…`).
> The odometry/EKF path depends on it byte-for-byte. `EVT …` lines are a **separate** channel.

---

## Parser — extend `processCommand()` in `main.cpp`

Today it only understands `V <l> <r>`. Add the aux branches. **Critical:** the 5-second drive
watchdog (`main.cpp`, `CMD_TIMEOUT_MS`) zeroes the motors if no command arrives — so refresh
`lastCmdMs` on **any** recognised command, or a multi-second `LIFT`/`STEP` move with no `V` traffic
will get cut off mid-move.

```cpp
static void processCommand(char* line) {
    if (toupper((unsigned char)line[0]) == 'V') {              // existing drive path
        float l = 0.f, r = 0.f;
        if (sscanf(line + 1, " %f %f", &l, &r) == 2) { cmdRpmL = l; cmdRpmR = r; }
    }
    else if (!strncmp(line, "LIFT ", 5)) lift.moveToMm(atof(line + 5));
    else if (!strcmp (line, "STEP EXT")) carriage.extend();
    else if (!strcmp (line, "STEP RET")) carriage.retract();
    else if (!strcmp (line, "PUMP ON"))  gripper.on();
    else if (!strcmp (line, "PUMP OFF")) gripper.off();
    else if (!strncmp(line, "SERVO ", 6)) { /* optional wheel nudge, no EVT */ }
    else if (!strcmp (line, "STOP")) {      // safety: halt aux immediately
        lift.stop();
        carriage.stop();
        gripper.off();
    }
    else return;                             // unknown → ignore, don't touch watchdog

    lastCmdMs = millis();                    // ANY recognised command re-arms the watchdog
}
```

Then call the updaters once per `loop()`:

```cpp
void loop() {
    // ... existing serial read + drive watchdog + velTick/outerTick ...

    carriage.run();     // AccelStepper.run() — must run every pass
    lift.update();      // non-blocking BTS7960 + limit-switch state machine
    carriage.update();  // emits EVT STEP DONE when a move finishes
    gripper.update();   // handles the valve-settle delay without blocking
}
```

---

## Non-blocking module sketches (drop into `firmware/src/`)

These mirror your tested logic; only the blocking parts are converted to `millis()` state. Fill in
the exact timings/heights from your bench tests.

### `LiftControl` (BTS7960 + limit switches) — timed like your `linear_acc` sketch
```cpp
class LiftControl {
  enum State { IDLE, EXTENDING, RETRACTING };
  State state = IDLE;
  uint32_t startMs = 0, durationMs = 0;
public:
  void begin() {
    pinMode(LIFT_RPWM,OUTPUT); pinMode(LIFT_LPWM,OUTPUT);
    pinMode(LIFT_REN,OUTPUT);  pinMode(LIFT_LEN,OUTPUT);
    digitalWrite(LIFT_REN,HIGH); digitalWrite(LIFT_LEN,HIGH);
    stop();
  }
  void moveToMm(float mm) {                       // convert mm → run time (your 5 mm/s)
    durationMs = (uint32_t)((mm / ACTUATOR_SPEED_MM_S) * 1000.0f);
    startMs = millis();
    if (mm > 0) { analogWrite(LIFT_LPWM,0); analogWrite(LIFT_RPWM,255); state = EXTENDING; }
    else        { analogWrite(LIFT_RPWM,0); analogWrite(LIFT_LPWM,255); state = RETRACTING; }
  }
  void stop() { analogWrite(LIFT_RPWM,0); analogWrite(LIFT_LPWM,0); state = IDLE; }
  void update() {
    if (state == EXTENDING && digitalRead(LIFT_TOP) == HIGH) {   // hardware failsafe first
      stop(); Serial.println("EVT FAULT lift top limit"); return;
    }
    if (state == RETRACTING && digitalRead(LIFT_BOTTOM) == HIGH) {
      stop(); Serial.println("EVT LIFT DONE"); return;           // reached home
    }
    if (state != IDLE && millis() - startMs >= durationMs) {
      stop(); Serial.println("EVT LIFT DONE");
    }
  }
};
```

### `CarriageControl` (AccelStepper) — keep homing, replace `delay()` debounce
```cpp
class CarriageControl {
  AccelStepper& s;
  bool moving = false;
public:
  CarriageControl(AccelStepper& st) : s(st) {}
  void extend()  { s.moveTo(+TRAVEL_STEPS); moving = true; }
  void retract() { s.moveTo(-TRAVEL_STEPS); moving = true; }
  void stop()    { s.stop(); moving = false; }
  void run()     { s.run(); }                     // call every loop()
  void update() {
    if (!moving) return;
    // limit switch OR target reached (use a millis() blind-window instead of delay debounce)
    if (s.distanceToGo() == 0 || limitHit()) {
      s.stop(); moving = false; Serial.println("EVT STEP DONE");
    }
  }
};
```

### `Gripper` (pump + valve relays) — valve settle without `delay(200)`
```cpp
class Gripper {
  enum Phase { OFF, VALVE_OPENING, ON } phase = OFF;
  uint32_t phaseMs = 0;
public:
  void begin() { pinMode(PUMP_RELAY,OUTPUT); pinMode(VALVE_RELAY,OUTPUT); off(); }
  void on()  { digitalWrite(VALVE_RELAY,HIGH); phase = VALVE_OPENING; phaseMs = millis(); }
  void off() { digitalWrite(PUMP_RELAY,LOW); digitalWrite(VALVE_RELAY,LOW);
               phase = OFF; Serial.println("EVT PUMP OFF"); }
  void update() {
    if (phase == VALVE_OPENING && millis() - phaseMs >= 200) {   // was delay(200)
      digitalWrite(PUMP_RELAY,HIGH); phase = ON; Serial.println("EVT PUMP ON");
    }
  }
};
```

---

## How to test your side (no ROS, no laptop stack needed)
1. Flash, open the PlatformIO serial monitor at **115200**.
2. Confirm `V 30 30` still drives the wheels exactly as before (regression — don't break drive!).
3. Type each aux command straight into the monitor and watch for the `EVT`:
   - `LIFT 100` → lift extends → `EVT LIFT DONE`
   - `STEP EXT` → `EVT STEP DONE`;  `PUMP ON` → `EVT PUMP ON`;  `PUMP OFF` → `EVT PUMP OFF`
   - `STOP` mid-move → motion halts immediately.
4. Confirm the telemetry line is unchanged and a `LIFT` move does **not** get cut off after 5 s.

When that passes, I plug it into the ROS bridge and the coordinator drives the full mission.
Ping me with the real lift heights (mm) and any timing you tuned so I can set the coordinator params.
