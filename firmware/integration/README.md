# firmware/integration — unified Teensy 4.1 firmware (drive + lift)

This project is the one firmware image meant to be flashed onto the robot's
Teensy 4.1. It owns the drive PID + odometry (already proven, unchanged from
`firmware/src/`), the scissor lift, and — as of this pass — the stepper
carriage (suction-cup cup) and vacuum pump/valve. `SERVO <deg>` (vision's
cup-centring nudge) is the only piece not wired in yet — see
[What's not here yet](#whats-not-here-yet).

## Why this project exists

The robot's hardware was tested in three separate places:

- **Wheels + IMU** — `firmware/src/` (Teensy 4.1), proven and currently the
  one running on the physical robot for Nav2 testing.
- **Linear actuator (lift)** — `linear_acc` branch, tested standalone on an
  ESP32 dev board.
- **Stepper + vacuum pump** — `stepper_motor_test` branch (commit `4167a67`,
  `firmware/stepper_motor/src/main.cpp`), tested on its own ESP32 as a
  free-running ping-pong demo (extend → grip → retract → release → repeat).

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
| Left encoder (A/B) | 22 / 23 |
| BNO055 IMU (SDA/SCL) | 18 / 19 |

Left encoder is `22 / 23`, not the more intuitive `23 / 22` — bench testing
found the initial `A=23 / B=22` wiring counted backward (drove the PID's
velocity loop off a wrong-signed measurement), so the constructor in
`main.cpp` was swapped to `Encoder leftEnc(22, 23)` to correct it.

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

New, for the stepper carriage + vacuum gripper (the `stepper_motor_test` ESP32
sketch used pins 26/27 (step/dir), 18/19 (pump/valve relay), 32/33
(limit switches). On this Teensy, 18/19 are already the BNO055 I2C bus and
26/27 ended up used elsewhere on this build, so step/dir moved to 36/37 and
the relays moved to 40/41 — the limit switches kept their original 32/33):

| Signal | Pin |
|---|---|
| Stepper TB6600 PUL+ (step) | 36 |
| Stepper TB6600 DIR+ | 37 |
| Pump relay | 40 |
| Valve relay | 41 |
| Stepper home limit switch (retracted) | 32 |
| Stepper max limit switch (extended) | 33 |

Unlike the lift, the stepper carriage keeps **both** limit switches — every
extend/retract drives all the way to a switch rather than a timed guess, so
there's no open-loop drift to bound in the first place.

All constants live in [`src/Config.h`](src/Config.h) — that's the one place
to change them if the physical wiring differs.

## Power & wiring guide

Read this before connecting a battery. It covers the full physical hookup:
power architecture, which wires need to be thick vs thin, grounding, and the
TB6600 DIP switches.

### Power architecture

```
24V battery pack (+ / −)
   │
   ├── B+/B− → Right BTS7960 (drive)  ── M+/M− → right drive motor
   ├── B+/B− → Left  BTS7960 (drive)  ── M+/M− → left  drive motor
   ├── B+/B− → Lift  BTS7960          ── M+/M− → scissor actuator
   └── separate stepper/pump supply (per their own voltage/current specs)
         ├── → TB6600 VMOT/GND  ── A+/A−/B+/B− → NEMA stepper
         └── → relay COM (switched load side, pump + valve)

Teensy 4.1 5V/3.3V logic rails power: BTS7960 VCC (3.3V — NOT 5V), TB6600
control side (PUL+/DIR+), limit switches (INPUT_PULLUP, no external supply
needed), relay IN pins.
```

**All grounds — 24V−, stepper/pump supply−, TB6600 GND, BTS7960 GND, relay
GND, Teensy GND — must be commoned.** A floating signal ground between the
Teensy and any driver is the single most common cause of "motor doesn't
move" / "motor moves randomly" bugs.

### Thick wire vs thin wire

| Wire | Carries | Gauge (min) | Why |
|---|---|---|---|
| 24V battery → each BTS7960 B+/B− | Full drive/actuator current (continuous amps, spikes higher under load) | 14–16 AWG | Heating/voltage drop scale with current — undersized power wire is a fire/brownout risk, not just inefficiency |
| BTS7960 M+/M− → motor/actuator | Same current as above | 14–16 AWG | Same reasoning |
| Stepper supply → TB6600 VMOT/GND, and TB6600 → stepper coils | Stepper current (set by DIP switches, ≤4A typ.) | 18–20 AWG | Lower current than drive motors, still a power line |
| Relay COM/NO → pump/valve | Whatever the pump/valve draws — check its nameplate | 18–20 AWG | — |
| RPWM/LPWM/R_EN/L_EN (BTS7960 control) | A few mA, logic only | 22–26 AWG | Signal only |
| PUL+/DIR+ (TB6600 control) | A few mA (opto LED current) | 22–26 AWG | Signal only |
| Limit switches, encoders, I2C | A few mA | 22–26 AWG | Signal only |
| Common ground return between boards | Logic return current | 20–22 AWG, keep it short | Reference, not power, but don't go thinner than the signal pair it serves |

Rule of thumb: **anything running between a battery/supply and a motor
terminal is thick wire (14–20 AWG depending on the load); anything that's a
control/logic signal between the Teensy and a driver is thin wire
(22–26 AWG)** — thin is actually preferable there, it's easier to route
around the chassis without stressing headers/connectors.

### TB6600 stepper driver — DIP switches

Six switches: SW1–SW3 set motor **current**, SW4–SW6 set **microstepping**.
Tables can vary slightly between clone boards — cross-check against your
board's silkscreen/datasheet if these don't match.

**Microstep (SW4/SW5/SW6) — this firmware requires 1/16 step:**

| SW4 | SW5 | SW6 | Microstep | Steps/rev (200 spr motor) |
|---|---|---|---|---|
| ON | ON | ON | Full step | 200 |
| OFF | ON | ON | 1/2 | 400 |
| ON | OFF | ON | 1/4 | 800 |
| OFF | OFF | ON | 1/8 | 1600 |
| **ON** | **ON** | **OFF** | **1/16 ← required** | **3200** |
| OFF | ON | OFF | 1/32 | 6400 |

`STEPPER_MAX_SPEED_SPS` / `STEPPER_ACCELERATION` / the 400-steps/mm
lead-screw math in `Config.h` all assume 3200 steps/rev. Any other
microstep setting desyncs the firmware's speed/mm from the real motor
speed — it'll still run, just at the wrong physical speed.

**Current (SW1/SW2/SW3) — match your stepper's rated phase current (its
nameplate, e.g. "1.8A/phase"):**

| SW1 | SW2 | SW3 | Current |
|---|---|---|---|
| ON | ON | ON | 0.5A |
| ON | ON | OFF | 1.0A |
| ON | OFF | ON | 1.5A |
| ON | OFF | OFF | 2.0A |
| OFF | ON | ON | 2.5A |
| OFF | ON | OFF | 3.0A |
| OFF | OFF | ON | 3.5A |
| OFF | OFF | OFF | 4.0A |

Set this **at or just below** the motor's rated current — over-setting runs
it hotter than spec (cooks the windings over time); under-setting loses
torque and causes skipped steps under load.

### TB6600 signal wiring — common cathode

This build is wired **common cathode**: `PUL−`/`DIR−`/`ENA−` on the TB6600
are tied together to a shared GND, and the Teensy drives `PUL+`→pin 36,
`DIR+`→pin 37 directly as active-HIGH pulses. This matches
`StepperControl.h`'s `stepper_.setPinsInverted(true, false, false)` — the
`stepInvert` argument (2nd) is `false`, i.e. un-inverted/active-HIGH pulses,
which is only correct for this common-cathode wiring. The `true` (1st
argument) is unrelated to cathode/anode — it only fixes which physical
direction AccelStepper calls "positive" so `+steps == extend`.

`ENA+`/`ENA−` are left unconnected — this firmware never drives a stepper
enable pin, so the TB6600 must be wired/jumpered to stay enabled by default.

### BTS7960 (drive ×2 + lift, 3 total)

- `VCC` → Teensy **3.3V**, never 5V (Teensy 4.1 pins are not 5V tolerant).
- `GND` → common ground rail.
- `RPWM`/`LPWM` → Teensy PWM pins (forward/reverse).
- `R_EN`/`L_EN` → Teensy digital pins, driven active-HIGH by `MotorDriver::begin()` / `LiftControl::begin()`.
- `B+`/`B−` → 24V supply (thick wire).
- `M+`/`M−` → motor/actuator terminals (thick wire; swap the two to flip default direction instead of touching code).
  On this robot **both** drive BTS7960 units turned out to have RPWM wired as
  the reverse direction (not forward, as first assumed for the right motor) —
  bench testing showed the right wheel spinning backward under a positive
  target. Rather than reswap the leads, this was corrected in software: both
  `MotorController` instances in `main.cpp` are constructed with
  `motorInverted=true`, which negates duty before it reaches `setSpeed()`.

### Relays (pump/valve)

- `IN` pins → Teensy 40 (pump) / 41 (valve), **active HIGH**.
- Switched side (`COM`/`NO`/`NC`) wired per your pump/valve's own voltage —
  confirm it's isolated from the 24V motor rail unless the pump/valve is
  actually rated for 24V.

### Limit switches

All four (lift bottom=34, stepper home=32, stepper max=33) are wired
**normally-closed to GND**, read via `INPUT_PULLUP`: LOW = closed (clear),
HIGH = open (triggered **or** wire cut — deliberate, so a severed wire reads
as "triggered" instead of silently reading "clear").

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

### `src/StepperControl.h` *(new)*
Ported from `stepper_motor_test`'s TB6600 + `AccelStepper` driver. Unlike the
lift, this is **not** open-loop timing — both `extend()` and `retract()` always
drive toward a limit switch (`STEPPER_MAX_PIN` / `STEPPER_HOME_PIN`) rather
than a computed distance, so every move is self-correcting and there's no
drift to bound. The original test sketch was a free-running ping-pong demo
(extend → grip → retract → release → repeat) with the grip/release baked into
the same state machine; here motion is split out and driven by explicit
`STEP EXT` / `STEP RET` commands, since `coordinator_node.py` sequences motion
and gripping as separate steps.

The test sketch's switch debounce used a blocking `delay(20)` — fine
standalone, but the same problem as the lift's original hand-off sketch: it
would stall the serial reader and block `STOP` mid-move. `StepperControl`
uses the same `millis()`-based blind-window + debounce pattern as
`LiftControl` instead.

Homes itself at boot the same way the lift does (creep to the bottom switch,
back off, zero), emitting `EVT STEP DONE` once — same event name a commanded
`STEP EXT`/`STEP RET` uses, since the coordinator only cares about the prefix.

### `src/PumpControl.h` *(new)*
The vacuum gripper's two relays (pump + solenoid valve), also ported from
`stepper_motor_test`. `pumpOn()` opens the valve, waits `VALVE_SETTLE_MS` for
it to physically seat, then energizes the pump (`EVT PUMP ON`). `pumpOff()`
cuts the pump, holds the valve shut for `PUMP_VENT_SETTLE_MS` so suction bleeds
off in a controlled way, then vents (`EVT PUMP OFF`). Both non-blocking,
`millis()`-timed, same reasoning as everywhere else in this project.

`stop()` is deliberately a no-op: `STOP` is an e-stop for **motion**
(drive/lift/stepper). If the gripper is mid-hold when `STOP` fires, cutting
the pump would drop whatever it's holding — releasing a grip has to be a
deliberate `PUMP OFF`, never a side effect of an emergency stop.

### `src/main.cpp`
Wheels loop (serial receive, 5 s command watchdog, 50 Hz velocity PID ramp,
20 Hz telemetry) is unchanged from `firmware/src/main.cpp`. Two additions:

1. `processCommand()` gained branches alongside the existing `V <l> <r>`:
   - `LIFT <mm>` → `lift.moveToMm(...)`
   - `PICK` / `DROP` → `lift.moveToMm(PICK_LIFT_MM)` / `lift.moveToMm(DROP_LIFT_MM)`
   - `STEP EXT` / `STEP RET` → `stepperCarriage.extend()` / `.retract()`
   - `PUMP ON` / `PUMP OFF` → `pump.pumpOn()` / `.pumpOff()`
   - `STOP` → `lift.stop()` **and** `stepperCarriage.stop()` **and** zeroes
     `cmdRpmL`/`cmdRpmR`, so one `STOP` halts drive + lift + stepper together.
     It deliberately does **not** touch the pump/valve — see
     `PumpControl::stop()` above.

   Every branch refreshes `lastCmdMs` (the drive watchdog timestamp) the same
   way the `V` branch already did, per the hand-off doc's warning.

   `SERVO <deg>` is the only command still **not implemented** — it falls
   through and is ignored, same as any unrecognized line.

2. `loop()` gained: `lift.update(); stepperCarriage.update(); pump.update();`,
   called every pass, right after the serial-receive block.

The 6-field telemetry line (`L_RPM:… R_RPM:… Hdg:… Dist:… Lcnt:… Rcnt:…`) is
byte-for-byte unchanged — the ROS-side odometry/EKF parsing depends on it.

## What's not here yet

- **`SERVO <deg>`** — optional per the hand-off doc; it's vision's job to
  stream centering corrections, and the mission completes without it (the
  cup just won't get a final nudge).

## How to test

### 1. Build & flash
No PlatformIO CLI in most dev shells for this repo — use the **PlatformIO
extension in VS Code**: open this folder, **Build** (compiles for
`env:teensy41`; the first build also pulls `lib_deps` — Encoder, Adafruit
BNO055, Adafruit Unified Sensor, AccelStepper), then **Upload** with the
Teensy plugged in.

### 2. Wiring checklist before powering the actuator / carriage
See [Power & wiring guide](#power--wiring-guide) above for the full
rundown (power architecture, wire gauge, grounding, DIP switches). Quick
pre-power checklist:
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
- TB6600 stepper driver: PUL+→36, DIR+→37, PUL-/DIR- → common GND
  (common-cathode wiring). **Set the DIP switches to 1/16 microstep
  (SW4=ON, SW5=ON, SW6=OFF)** and the current switches (SW1-3) to match your
  motor's rated current — before the first powered test, since the motion
  profile in `Config.h` assumes 1/16 microstep specifically.
- Stepper home/max limit switches → 32/33, same NC-to-GND / `INPUT_PULLUP`
  wiring as the lift's bottom switch.
- Pump relay → 40, valve relay → 41, both active HIGH. **Do not wire these to
  18/19** — those are the IMU's I2C bus on this board (that's exactly the
  collision this re-map exists to avoid).
- Manually press both stepper limit switches by hand before the first powered
  test, same reasoning as the lift's bottom switch.

### 3. Open the serial monitor
115200 baud, **Newline** line ending (commands are only processed once a
`\n`/`\r` is seen). On boot you should see:
```
=== AMR ROS2 Listener — booting ===
IMU OK. Waiting for velocity commands...
```
followed by one `EVT LIFT DONE` (the auto-home in `lift.begin()`) and one
`EVT STEP DONE` (the auto-home in `stepperCarriage.begin()`) shortly after —
order between the two isn't guaranteed, both are just re-homing at boot. If it
hangs on `FATAL: BNO055 IMU not found`, that's the wheels IMU wiring
(SDA=18/SCL=19) — unrelated to the lift/stepper, but `setup()` won't reach
either `begin()` until it's fixed.

### 4. Test sequence

| Command | Expected result |
|---|---|
| `V 30 30` | Wheels spin, telemetry keeps printing at 20 Hz — **regression check** |
| `V 0 0` | Wheels stop |
| `LIFT 100` | Extends for ~23 s (100 mm ÷ 4.38 mm/s) → `EVT LIFT DONE` |
| `LIFT 0` | Retracts until the bottom switch **physically** triggers → `EVT LIFT DONE` (this is the real re-home path — confirm it stops exactly at the switch, not seconds early) |
| `LIFT 120` (from 0) | Extends ~27 s → `EVT LIFT DONE` |
| `LIFT 434` (from 0) | Extends fully to the rail's physical limit (~99 s at 4.38 mm/s) → `EVT LIFT DONE` — confirm it doesn't strain against the end stop for longer than a moment |
| `PICK` | Lift moves to `PICK_LIFT_MM` → `EVT LIFT DONE` |
| `DROP` | Lift moves to `DROP_LIFT_MM` → `EVT LIFT DONE` |
| `STEP EXT` | Carriage drives out until the max limit switch fires → `EVT STEP DONE` |
| `STEP RET` | Carriage drives in until the home limit switch fires → `EVT STEP DONE` (confirm it stops exactly at the switch) |
| `PUMP ON` | Valve opens, ~200 ms later pump engages → `EVT PUMP ON` — listen/feel for suction |
| `PUMP OFF` | Pump cuts, ~500 ms later valve vents → `EVT PUMP OFF` |
| `STOP` mid-move | Halts drive/lift/stepper immediately, **no** `EVT` printed. If gripping, suction stays on (see `PumpControl::stop()`) |

Watch the telemetry line throughout — its format must never change, even
mid-move.

### Safety notes for the first physical run
- This is open-loop/timed with **no top limit switch and no position
  encoder** — if the timing estimate is ever wrong (voltage sag, added load,
  wear), nothing in firmware stops an over-extend except the rail's physical
  end stop. Keep a hand on the power switch for the first few `LIFT`
  commands, especially any near `LIFT_MAX_TRAVEL_MM`.
- Test unloaded (no scissor arm load / no box) for the first pass — for both
  the lift and the stepper carriage.
- Verify `STOP` works early — it's the one command that bypasses timing and
  cuts PWM/steps immediately, so it's your abort button for the rest of
  testing. Remember it does **not** release the vacuum grip — use `PUMP OFF`
  for that.
- Test `PUMP ON`/`PUMP OFF` with something light and disposable before
  trusting it on an actual box — confirm the valve/pump ordering feels right
  (valve-open-then-pump-on to grip, pump-off-then-valve-vent to release).

Once the table above passes, the next step is exercising it through
`serial_bridge_node` + `coordinator_node` with `vision_stub` faking the QR
checks, before adding the stepper carriage and vacuum gripper.
