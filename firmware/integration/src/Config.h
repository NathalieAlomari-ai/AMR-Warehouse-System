#pragma once

// =============================================================================
// Config.h — Robot physical constants. Edit here; nowhere else.
//
// HOW TO MEASURE ENCODER_PPR:
//   Mark the output shaft. Spin it one full revolution by hand.
//   Count the raw pulses on channel A with a scope or Serial.print in setup().
//   Multiply by 4 for quadrature. That number is ENCODER_PPR.
//   Typical 775-class planetary motor: (11 encoder lines × 4) × 30:1 = 1320.
// =============================================================================

// Encoder pulses per full revolution of the OUTPUT shaft (after gearbox).
static constexpr int   ENCODER_PPR       = 2700;

// Physical dimensions — measure your actual robot
static constexpr float WHEEL_DIAMETER_M  = 0.125f;   // metres
static constexpr float WHEEL_BASE_M      = 0.65f;    // metres (wheel centre-to-centre)

// Derived — do not edit
static constexpr float WHEEL_CIRCUMF_M   = WHEEL_DIAMETER_M * 3.14159265f;
static constexpr float COUNTS_PER_METER  = (float)ENCODER_PPR / WHEEL_CIRCUMF_M;

// Free-run max RPM at full duty (255) — measured from telemetry on the floor:
//   Left:  FF duty = target/75×255 = 104  →  actual 62.7 RPM  →  max = 62.7×255/104 ≈ 154
//   Right: FF duty = target/60×255 = 130  →  actual 75.7 RPM  →  max = 75.7×255/130 ≈ 149
// Both motors measure ~150 RPM free-run max.  Using one shared value means
// both motors receive identical FF duty for any target, so the PID only needs
// to trim the small difference caused by per-motor friction.
//
// HOW TO RECALIBRATE if motors feel sluggish or over-fast:
//   Drive at a steady speed, note telemetry RPM and the telemetry duty (add
//   'duty' to Serial.print in main.cpp if needed).
//   MAX_RPM = observed_RPM × 255 / observed_duty
static constexpr float MAX_RPM_LEFT      = 150.0f;
static constexpr float MAX_RPM_RIGHT     = 150.0f;

// Velocity PID gains.
// Kp: immediate proportional correction to RPM error.
// Ki: integrates away persistent motor-to-motor differences (floor friction etc.).
// Kd: keep at 0 — derivative on per-tick encoder counts is pure noise.
//
// Tuning guide:
//   Still drifts after 3 s   → raise Ki (try 1.5)
//   Motors oscillate/shake   → lower Kp (try 0.5)
//   Slow to correct          → raise Kp (try 1.2)
static constexpr float VEL_KP            = 0.8f;
static constexpr float VEL_KI            = 1.0f;
static constexpr float VEL_KD            = 0.0f;
// With MAX_RPM calibrated to true free-run, FF is accurate and residual
// error is only 3–8 RPM (floor friction difference between motors).
// ICLAMP=30 provides up to 30 duty units of integral correction — plenty.
static constexpr float VEL_ICLAMP        = 30.0f;

// =============================================================================
// Lift (scissor linear actuator) — BTS7960 + 1 limit switch.
//
// Pins per docs/HANDOFF_zahra_firmware.md — the ESP32 test sketch reused pins
// 18/19/21/22/32, which on this Teensy are already the BNO055 I2C bus and the
// quadrature encoders. These are the re-mapped, conflict-free pins.
//
// No top limit switch: full-range (min retracted -> max extended) timing was
// bench-verified directly on the assembled scissor lift, so the top switch was
// dropped as an unneeded failsafe. The bottom switch stays — it's not really a
// safety switch, it's the only re-homing reference in the system. Every
// "LIFT 0" retracts until it fires, which bounds the open-loop drift that
// would otherwise accumulate across a long mission's repeated partial moves
// (e.g. shelf 200 -> home 0 -> drop-off 120 -> home 0 -> ...).
// =============================================================================
static constexpr int   LIFT_RPWM         = 28;   // extend  (PWM)
static constexpr int   LIFT_LPWM         = 29;   // retract (PWM)
static constexpr int   LIFT_REN          = 30;
static constexpr int   LIFT_LEN          = 31;
static constexpr int   LIFT_BOTTOM       = 34;   // 0 mm / home limit switch

// Measured on the assembled unit with the scissor + ~10 kg working load
// attached (open-loop, no encoder on the actuator itself — position is
// estimated from commanded run time and re-zeroed whenever the bottom limit
// switch fires). Units are mm of ACTUATOR ROD travel, not scissor/platform
// height — the two differ because the scissor linkage isn't 1:1.
//
// The rod's true physical travel is 0-444mm, NOT 500mm as first assumed —
// confirmed by running the bare actuator straight off a power supply and
// watching it refuse to extend past 44.4cm. That correction also feeds back
// into both speed constants below.
//
// Load makes the two directions asymmetric, so timing needs separate speeds
// instead of one shared constant. Both are calibrated from clean, direct
// full-stroke (0mm <-> 444mm) timings, each with 1s subtracted from the
// stopwatch reading to account for human reaction lag stopping the watch
// (a fixed lag reads as a bigger relative error on the shorter measurement,
// which is part of why the raw numbers still undershot the true speed):
//   - Extending fights gravity + the 10kg load: full stroke home -> max,
//     stopwatch 102.46s -> 101.46s corrected -> 444/101.46 = ~4.38 mm/s.
//   - Retracting is gravity-assisted (lowering the load): full stroke max ->
//     home, stopwatch 98.86s -> 97.86s corrected -> 444/97.86 = ~4.54 mm/s.
//
// This is pure open-loop timing with no position encoder, so any leftover
// calibration error is a *percentage* of speed, which means its effect in
// mm grows with move distance — e.g. a 1% speed error is ~1mm off on a
// 120mm move but ~4mm off on a full 434mm move. That residual proportional
// drift can't be fully eliminated without a position sensor; re-homing
// (LIFT 0) between moves is what bounds it for real missions, since those
// moves are much shorter than a full-stroke test.
static constexpr float ACTUATOR_EXTEND_SPEED_MM_S  = 4.38f;
static constexpr float ACTUATOR_RETRACT_SPEED_MM_S = 4.54f;

// Actuator's own physical rod travel is 0-444mm (measured directly off a
// power supply, independent of the scissor). Kept ~10mm below that true
// mechanical stop since this clamp has no hardware backup (no top switch) —
// the previous 490mm value was still above the real stop and was driving
// the actuator into it, stalling there for the remainder of the commanded
// run instead of stopping cleanly.
static constexpr float LIFT_MAX_TRAVEL_MM   = 434.0f;

// =============================================================================
// Presentation-fixed pick/drop heights — for the demo scenario the lift always
// goes to one of exactly two known table heights, so the Teensy owns the
// target mm values instead of the Jetson computing/sending them.
//
// Table heights are ground -> table surface. The robot's own ground -> top-
// of-scissor height was measured at the actuator's two travel extremes:
//   - fully retracted (0mm actuator): 78cm
//   - fully extended (444mm actuator, true stroke — see LIFT_MAX_TRAVEL_MM
//     note above): 132.4cm
// That gives a platform-height range of 54.4cm (544mm) across the full
// 444mm actuator stroke — the scissor linkage isn't 1:1, so a target table
// height is converted to actuator mm via that ratio (linear interpolation
// between the two measured endpoints only; unverified in between).
//
// PICK_TABLE_HEIGHT_MM (76cm) is BELOW the platform's reachable minimum
// (78cm at full retraction) — even fully home, the platform sits 2cm above
// it. PICK_LIFT_MM below computes negative for this reason and relies on
// moveToMm()'s existing constrain() to floor it to 0 (home). That means the
// "pick" position will actually be ~78cm, not 76cm, until either the table
// is confirmed to really be ~78cm or there's a gripper reach/offset below
// the scissor top that closes this 2cm gap — verify this on the bench
// before relying on it live.
static constexpr float SCISSOR_HOME_HEIGHT_MM  = 780.0f;   // ground->top-of-scissor @ 0mm actuator (78cm)
static constexpr float SCISSOR_MAX_HEIGHT_MM   = 1324.0f;  // ground->top-of-scissor @ 444mm actuator (132.4cm)
static constexpr float SCISSOR_HEIGHT_RANGE_MM = SCISSOR_MAX_HEIGHT_MM - SCISSOR_HOME_HEIGHT_MM;   // 544mm
static constexpr float ACTUATOR_FULL_STROKE_MM = 444.0f;   // true measured rod stroke (not the 434mm safety clamp)

static constexpr float PICK_TABLE_HEIGHT_MM = 760.0f;  // 76cm — see caveat above
static constexpr float DROP_TABLE_HEIGHT_MM = 880.0f;  // 88cm

static constexpr float PICK_LIFT_MM = (PICK_TABLE_HEIGHT_MM - SCISSOR_HOME_HEIGHT_MM) * (ACTUATOR_FULL_STROKE_MM / SCISSOR_HEIGHT_RANGE_MM);
static constexpr float DROP_LIFT_MM = (DROP_TABLE_HEIGHT_MM - SCISSOR_HOME_HEIGHT_MM) * (ACTUATOR_FULL_STROKE_MM / SCISSOR_HEIGHT_RANGE_MM);

// =============================================================================
// Stepper carriage (suction-cup extend/retract) + vacuum gripper.
// Ported from the `stepper_motor_test` branch (firmware/stepper_motor/src/main.cpp,
// commit 4167a67), which proved this out standalone on an ESP32 + TB6600 driver.
//
// That test sketch used pins 26/27 (step/dir), 18/19 (pump/valve relay), 32/33
// (home/max limit switches). On this Teensy, 18/19 are already the BNO055 I2C
// bus (SDA/SCL) and 26/27 ended up used elsewhere on this build, so step/dir
// moved to 36/37 and the relays moved to 40/41. The limit switches kept their
// original pins, 32/33 (lift only uses 28-31/34, so no conflict).
// =============================================================================
static constexpr int   STEPPER_STEP_PIN   = 36;   // TB6600 PUL+
static constexpr int   STEPPER_DIR_PIN    = 37;   // TB6600 DIR+
static constexpr int   STEPPER_HOME_PIN   = 32;   // bottom/retracted limit (re-homing reference)
static constexpr int   STEPPER_MAX_PIN    = 33;   // top/extended limit

static constexpr int   PUMP_RELAY_PIN     = 40;   // Relay 1 IN — active HIGH
static constexpr int   VALVE_RELAY_PIN    = 41;   // Relay 2 IN — active HIGH

// 1/16 microstep, 8mm lead screw -> 3200 steps/rev -> 400 steps/mm.
// !! HARDWARE: set TB6600 DIP switches to 1/16 microstep before running:
//    SW4=ON  SW5=ON  SW6=OFF
// Also set the current switches (SW1-3) to match the stepper's rated
// current — see README.md "Power & wiring guide" for the full DIP switch
// tables and common-cathode signal wiring (PUL+/DIR+ here, PUL-/DIR- to GND).
// Not used for distance math below — both EXTEND and RETRACT drive toward a
// limit switch, not a computed distance, same as the proven test sketch.
static constexpr float    STEPPER_MAX_SPEED_SPS   = 3200.0f;  // 8 mm/s   — normal moves
static constexpr float    STEPPER_HOMING_SPEED_SPS = 400.0f;  // 1 mm/s   — slow creep during homing
static constexpr float    STEPPER_ACCELERATION     = 2400.0f; // 6 mm/s²
static constexpr long     STEPPER_TRAVEL_STEPS     = 1000000L; // "move until a limit switch fires"
static constexpr long     STEPPER_UNPRESS_STEPS    = 200L;     // back off after home switch contact

// Same non-blocking debounce shape as LiftControl: ignore switch reads for
// SWITCH_BLIND_MS after a move starts (driver-on noise spike), then require
// the read to hold HIGH for SWITCH_DEBOUNCE_MS before trusting it. The proven
// test sketch used a blocking delay(20) for this; that's fine standalone but
// unacceptable here since it would stall the serial reader and block STOP
// mid-move, same reasoning as LiftControl's homing debounce.
static constexpr uint32_t STEPPER_SWITCH_BLIND_MS    = 500;
static constexpr uint32_t STEPPER_SWITCH_DEBOUNCE_MS = 20;

// Vacuum gripper timing (from the test sketch): the solenoid valve needs a
// moment to physically open before the pump engages, and after the pump is
// cut, the valve stays shut briefly before venting (lets suction bleed off
// in a controlled way rather than an instant pop).
static constexpr uint32_t VALVE_SETTLE_MS      = 200;   // valve open -> pump on
static constexpr uint32_t PUMP_VENT_SETTLE_MS  = 500;   // pump off -> valve vent
