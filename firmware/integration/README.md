# firmware/integration — unified Teensy 4.1 firmware (drive + lift)

This project is the one firmware image meant to be flashed onto the robot's
Teensy 4.1. It owns the drive PID + odometry (already proven, unchanged from
`firmware/src/`) and, as of this pass, the scissor lift. Stepper carriage
(suction-cup cup) and vacuum pump/valve are not wired in yet — see
[What's not here yet](#whats-not-here-yet).

## Why this project exists

The robot's hardware was tested in three separate places:

- **Wheels + IMU** — `firmware/src/` (Teensy 4.1), proven and currently the
  one running on the physical robot for Nav2 testing.
- **Linear actuator (lift)** — `linear_acc` branch, tested standalone on an
  ESP32 dev board.
- **Stepper + vacuum pump** — `stepper_motor_test` branch, also tested on its
  own ESP32.

Only one program is allowed to own the robot's single USB serial line
(`/dev/ttyACM0`) — that's `serial_bridge_node` on the ROS side — so all of the
hardware above has to live on **one board**, driven by **one firmware image**.
That's what `firmware/integration/` is: the wheels code plus the lift code,
merged onto the Teensy, talking one serial protocol.

The full spec for this port — wire protocol, pin re-map, and starter code —
was written up by Nathalie (ROS2/mission side) for Zahra (firmware side) in
[`docs/HANDOFF_zahra_firmware.md`](../../docs/HANDOFF_zahra_firmware.md).
This project follows that spec, with one correctness fix explained below.

## How the pieces fit together (system view)

```
 coordinator_node.py  ──/aux/command──▶  serial_bridge_node.py  ──USB serial──▶  Teensy (this firmware)
        ▲                                       │
        │                                  /aux/status
        └───────────────────────────────────────┘
```

- `coordinator_node.py` runs the mission FSM (Nav2 → shelf QR → **lift up** →
  box QR → step/pump → **lift down** → Nav2 → drop-off → home) and sends
  plain strings like `LIFT 200`.
- `serial_bridge_node.py` is the only process that opens the serial port. It
  forwards `/aux/command` straight to the Teensy, unchanged, and republishes
  any Teensy line starting with `EVT ` onto `/aux/status`. Everything else
  coming from the Teensy is treated as the existing 20 Hz odometry telemetry.
- This firmware is what has to understand `LIFT <mm>` / `STOP` and reply with
  `EVT LIFT DONE` — that contract is what makes the mission coordinator's
  blocking wait-for-completion logic work.

## Pin map

Already in use by the wheels/IMU — **do not reuse these**:

| Signal | Pin(s) |
|---|---|
| Right BTS7960 (RPWM/LPWM/R_EN/L_EN) | 2 / 3 / 4 / 5 |
| Left BTS7960 (RPWM/LPWM/R_EN/L_EN) | 6 / 7 / 8 / 9 |
| Right encoder (A/B) | 20 / 21 |
| Left encoder (A/B) | 23 / 22 |
| BNO055 IMU (SDA/SCL) | 18 / 19 |

New, for the lift (the ESP32 test sketch used 18/19/21/22/32 — all of which
collide with the list above, hence the re-map):

| Signal | Pin |
|---|---|
| Lift BTS7960 RPWM (extend) | 28 (PWM) |
| Lift BTS7960 LPWM (retract) | 29 (PWM) |
| Lift BTS7960 R_EN | 30 |
| Lift BTS7960 L_EN | 31 |
| Lift bottom limit switch (0 mm / home) | 34 |

There is deliberately **no top limit switch** — see
[`src/LiftControl.h`](#srcliftcontrolh-new) below for why.

All constants live in [`src/Config.h`](src/Config.h) — that's the one place
to change them if the physical wiring differs.

## Code walkthrough

### `src/Config.h`
Physical constants only — encoder counts, wheel geometry, PID gains (all
copied verbatim from `firmware/src/Config.h`), plus the lift block added in
this pass: the five pins above, `ACTUATOR_EXTEND_SPEED_MM_S = 4.38` /
`ACTUATOR_RETRACT_SPEED_MM_S = 4.54` (measured on the assembled unit under
the scissor's ~10kg working load — extending fights gravity+load, retracting
is gravity-assisted, so they're not the same speed), and
`LIFT_MAX_TRAVEL_MM = 434.0` (~10mm under the actuator's true 444mm physical
rod travel, confirmed by running the bare actuator off a power supply — the
rod does not reach 500mm as first thought). With no top switch,
`LIFT_MAX_TRAVEL_MM` is now a **software-only** clamp — it stops a
bad/out-of-range command from asking
for more travel than the rail has, but nothing hardware-side backs it up
anymore.

### `src/DriveSystem.h`, `MotorController.h`, `MotorDriver.h`, `PIDController.h`
Copied byte-for-byte from `firmware/src/` — this is the classmate-tuned,
Nav2-proven drive stack (cascade velocity PID + BNO055 heading + encoder
odometry). Nothing here was touched; diffed identical against
`origin/feature/slam-setup`.

### `src/LiftControl.h` *(new)*
The BTS7960 scissor-lift driver. The actuator has **no position encoder** —
only the one bottom limit switch — so position is estimated open-loop from
commanded run time at `ACTUATOR_EXTEND_SPEED_MM_S` (extending) or
`ACTUATOR_RETRACT_SPEED_MM_S` (retracting).

This deviates from the literal example in the hand-off doc (which assumed
two limit switches) in two ways, one a correctness fix and one a deliberate
simplification after bench testing:

- **No top limit switch.** Full-range (min retracted → max extended) timing
  was verified directly on the assembled scissor lift, so the top switch —
  which was only ever a failsafe backstop — was dropped. `EXTENDING` and
  `RETRACTING` are both purely timed, no switch read during either — but they
  use different speed constants, since the load makes retracting faster
  (gravity-assisted) than extending (fighting gravity + load).
- **Delta-based moves, not absolute-duration.** The hand-off doc's sketch
  computes move duration from the **absolute** target every time
  (`duration = mm / speed`), which is only correct if every move starts from
  0. The actual mission sequence is 200 mm (shelf) → 0 mm (home, for transit)
  → 120 mm (drop-off) — none of which start from 0 except the first. So
  `LiftControl` tracks an estimated `currentPositionMm_` and computes
  `delta = target - currentPositionMm_`, timing the move for
  `|delta| / speed` seconds in the correct direction (extend or retract speed,
  whichever the sign of `delta` selects).

The bottom switch is kept — not really as a "safety" switch, but as the
**only re-homing reference** in the system. On `moveToMm(target)`, any
target at/near 0 triggers a **real home** (retract until the bottom switch
physically fires, no timing guess involved) instead of a timed move. That's
what bounds the open-loop drift that would otherwise accumulate across a
long mission's repeated partial moves — every "lift down" is a hard re-zero,
not an accumulating estimate.

- `update()` — called once per `loop()` pass, never blocks: during `HOMING`
  it checks the bottom switch (zeroes the position estimate and emits
  `EVT LIFT DONE`); during `EXTENDING`/`RETRACTING` it just checks whether
  the timer has elapsed.
- A short `millis()`-based "blind window" after starting a homing move
  ignores the bottom-switch read for 200 ms, so a power-on noise spike on
  the driver can't be mistaken for a real trigger. This is the same idea as
  the debounce in the tested `stepper_motor_test` sketch, but done without
  `delay()` — a real `delay()` here would stall the serial reader and block
  `STOP` from ever being processed mid-move, which the hand-off doc
  specifically calls out as unacceptable.
- `stop()` cuts PWM immediately and emits **no** event — matching the wire
  protocol's `STOP` contract (no completion event expected).

**Trade-off to be aware of:** with no top switch, nothing in firmware stops
an over-extend if the timing estimate is ever wrong (voltage sag, load,
wear) — it relies entirely on the bench-verified timing being right. If that
stops being true (e.g. the actuator or gearing changes), reinstating a top
switch is a small, self-contained change to `LiftControl::update()`.

### `src/main.cpp`
Wheels loop (serial receive, 5 s command watchdog, 50 Hz velocity PID ramp,
20 Hz telemetry) is unchanged from `firmware/src/main.cpp`. Two additions:

1. `processCommand()` gained two branches alongside the existing `V <l> <r>`:
   - `LIFT <mm>` → `lift.moveToMm(...)`
   - `STOP` → `lift.stop()` **and** zeroes `cmdRpmL`/`cmdRpmR` so `STOP` halts
     both subsystems, not just one.

   Both branches refresh `lastCmdMs` (the drive watchdog timestamp) the same
   way the `V` branch already did, per the hand-off doc's warning — otherwise
   a long `LIFT` move with no `V` traffic in between has no bearing on the
   watchdog anyway since drive and lift are independent, but this keeps the
   contract consistent for when `STEP`/`PUMP` land later and might need it.

   `STEP EXT` / `STEP RET` / `PUMP ON` / `PUMP OFF` / `SERVO <deg>` are **not
   implemented** — they simply fall through and are ignored, same as any
   unrecognized line. This is intentional for this pass, not an oversight.

2. `loop()` gained one line: `lift.update();`, called every pass, right
   after the serial-receive block.

The 6-field telemetry line (`L_RPM:… R_RPM:… Hdg:… Dist:… Lcnt:… Rcnt:…`) is
byte-for-byte unchanged — the ROS-side odometry/EKF parsing depends on it.

## What's not here yet

- **Stepper carriage** (extends/retracts the suction cup) and **vacuum
  pump/valve** (grip/release) — tested standalone in `stepper_motor_test`,
  not yet ported. `STEP`/`PUMP` commands are currently no-ops.
- **`SERVO <deg>`** — optional per the hand-off doc; it's vision's job to
  stream centering corrections, and the mission completes without it (the
  cup just won't get a final nudge).

## How to test

### 1. Build & flash
No PlatformIO CLI in most dev shells for this repo — use the **PlatformIO
extension in VS Code**: open this folder, **Build** (compiles for
`env:teensy41`; the first build also pulls `lib_deps` — Encoder, Adafruit
BNO055, Adafruit Unified Sensor), then **Upload** with the Teensy plugged in.

### 2. Wiring checklist before powering the actuator
- BTS7960 lift driver: RPWM→28, LPWM→29, R_EN/L_EN→30/31, driver VCC→**3.3V**
  (Teensy pins are not 5V tolerant).
- Bottom limit switch → 34, wired NC to GND (`INPUT_PULLUP`: LOW = clear,
  HIGH = triggered/wire-cut). There is no top switch — the rail's physical
  end stop is the only thing limiting over-extension, so double-check
  `ACTUATOR_EXTEND_SPEED_MM_S`/`ACTUATOR_RETRACT_SPEED_MM_S`/
  `LIFT_MAX_TRAVEL_MM` in `Config.h` still match reality before the first
  powered test.
- Manually press the bottom switch by hand before the first powered test and
  watch the serial monitor behavior in the next step — confirm the logic
  sense before trusting the re-home path.

### 3. Open the serial monitor
115200 baud, **Newline** line ending (commands are only processed once a
`\n`/`\r` is seen). On boot you should see:
```
=== AMR ROS2 Listener — booting ===
IMU OK. Waiting for velocity commands...
```
followed by one `EVT LIFT DONE` shortly after (the auto-home in
`lift.begin()`). If it hangs on `FATAL: BNO055 IMU not found`, that's the
wheels IMU wiring (SDA=18/SCL=19) — unrelated to the lift, but `setup()`
won't reach `lift.begin()` until it's fixed.

### 4. Test sequence

| Command | Expected result |
|---|---|
| `V 30 30` | Wheels spin, telemetry keeps printing at 20 Hz — **regression check** |
| `V 0 0` | Wheels stop |
| `LIFT 100` | Extends for ~23 s (100 mm ÷ 4.38 mm/s) → `EVT LIFT DONE` |
| `LIFT 0` | Retracts until the bottom switch **physically** triggers → `EVT LIFT DONE` (this is the real re-home path — confirm it stops exactly at the switch, not seconds early) |
| `LIFT 120` (from 0) | Extends ~27 s → `EVT LIFT DONE` |
| `LIFT 434` (from 0) | Extends fully to the rail's physical limit (~99 s at 4.38 mm/s) → `EVT LIFT DONE` — confirm it doesn't strain against the end stop for longer than a moment |
| `STOP` mid-move | Halts immediately, **no** `EVT` printed |

Watch the telemetry line throughout — its format must never change, even
mid-`LIFT`.

### Safety notes for the first physical run
- This is open-loop/timed with **no top limit switch and no position
  encoder** — if the timing estimate is ever wrong (voltage sag, added load,
  wear), nothing in firmware stops an over-extend except the rail's physical
  end stop. Keep a hand on the power switch for the first few `LIFT`
  commands, especially any near `LIFT_MAX_TRAVEL_MM`.
- Test unloaded (no scissor arm load / no box) for the first pass.
- Verify `STOP` works early — it's the one command that bypasses timing and
  cuts PWM immediately, so it's your abort button for the rest of testing.

Once the table above passes, the next step is exercising it through
`serial_bridge_node` + `coordinator_node` with `vision_stub` faking the QR
checks, before adding the stepper carriage and vacuum gripper.
