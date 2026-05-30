// =============================================================================
// AMR Firmware — Stage 3: 4-Layer Cascade PID + ROS2 Serial Bridge
// Hardware : Teensy 4.1 + 2× BTS7960 + 2× 775 Planetary Gear Motor (120 RPM)
//            + 2× Quadrature Encoder + Adafruit BNO055 IMU
// Payload  : Up to 60 kg
//
// WIRING MAP
// ----------
// Left Motor  (Driver 2):  RPWM→6  LPWM→7  R_EN→8  L_EN→9
//   Encoder A → Pin 10  |  Encoder B → Pin 11
//
// Right Motor (Driver 1):  RPWM→2  LPWM→3  R_EN→4  L_EN→5
//   Encoder A → Pin 14  |  Encoder B → Pin 15
//
// BNO055 IMU : I2C (SDA→18, SCL→19 on Teensy 4.1)
//
// ENCODER POLARITY:
//   Positive RPM = forward. If a motor reads negative when driving forward,
//   swap its Encoder constructor arguments (A ↔ B).
//
// CASCADE ARCHITECTURE (tune innermost layer first):
//
//   Layer 1 — Velocity PID (50 Hz, inside MotorController):
//     Target RPM  →  PWM duty cycle (0–255)
//
//   Layer 3 — Sync PID (20 Hz, DriveSystem::syncPID):
//     lCount − rCount error  →  ±RPM correction applied to both wheels
//
//   Layer 4 — Heading PID (20 Hz, DriveSystem::headingPID):
//     Heading error (°)  →  ±RPM differential correction
//     Active only during straight travel; suppressed when ROS2 commands rotation.
//
//   Layer 2 — Position PID (DriveSystem::posPID):
//     NOT used in serial-velocity mode (ROS2/Nav2 owns position externally).
//     Enable via drive.setTargetDistance() + drive.updateOuter() for
//     autonomous waypoint navigation without a live ROS2 connection.
//
// ROS2 SERIAL BRIDGE:
//   Incoming: <linear_x,angular_z>\n  at 115200 baud
//   Outgoing: [L_ticks,R_ticks,L_rpm,R_rpm]\n  at 20 Hz
//   Lines starting with '[' are machine-readable odometry; others are debug.
//
// QUICK-START TUNING SEQUENCE:
//   1. VEL_KP/KI/KD  — Kp until oscillation, back off 30%, then Kd, then Ki.
//   2. drive.syncPID  — Kp until wheels stay in sync during straight travel.
//   3. drive.headingPID — Kp/Kd until heading locks without yaw oscillation.
//   4. drive.posPID   — tune last, for autonomous mode only.
// =============================================================================

#include <Arduino.h>
#include <Encoder.h>
#include "Config.h"
#include "MotorDriver.h"
#include "PIDController.h"
#include "MotorController.h"
#include "DriveSystem.h"

// =============================================================================
// TUNING CONSTANTS — edit here before each test session
// =============================================================================

// Layer 1: Velocity PID — conservative starting values for 60 kg load.
// More authority (higher Kp) is needed to overcome heavy static friction.
static constexpr float VEL_KP = 2.0f;
static constexpr float VEL_KI = 0.10f;
static constexpr float VEL_KD = 0.05f;

// Layers 2–4 default gains live in DriveSystem.h constructor.
// Access via drive.posPID / drive.syncPID / drive.headingPID at runtime.

// Slew rate: maximum RPM change per second.
// 25 RPM/s → 0→120 RPM takes ~4.8 s, preventing current spikes under load.
static constexpr float MAX_RPM_STEP_PER_SEC = 25.0f;

// =============================================================================
// TIMING CONSTANTS
// =============================================================================

static constexpr unsigned long INNER_INTERVAL_US = 20000UL; // 50 Hz Velocity PID
static constexpr unsigned long OUTER_INTERVAL_MS = 50UL;    // 20 Hz outer PIDs
static constexpr unsigned long WATCHDOG_MS        = 500UL;  // Safety timeout
static constexpr unsigned long ODOM_MS            = 50UL;   // 20 Hz odometry output

// =============================================================================
// HARDWARE INSTANCES
// =============================================================================

// Quadrature encoders. Swap A↔B arguments if a motor reads negative RPM forward.
static Encoder encLeft (10, 11);
static Encoder encRight(14, 15);

// BTS7960 motor drivers: MotorDriver(RPWM, LPWM, R_EN, L_EN)
static MotorDriver driverLeft (6, 7, 8, 9);
static MotorDriver driverRight(2, 3, 4, 5);

// Motor controllers: velocity PID + encoder, one per wheel
static MotorController leftCtrl (driverLeft,  encLeft,  ENCODER_PPR);
static MotorController rightCtrl(driverRight, encRight, ENCODER_PPR);

// DriveSystem owns: posPID (L2), syncPID (L3), headingPID (L4), BNO055 IMU.
// All three outer PID objects are public — accessible as drive.syncPID etc.
static DriveSystem drive(leftCtrl, rightCtrl);

// =============================================================================
// CONTROL STATE
// =============================================================================

static float         _leftSetpoint  = 0.0f; // RPM commanded by outer loop
static float         _rightSetpoint = 0.0f;
static float         _leftRamped    = 0.0f; // Slew-rate-limited RPM fed to velPID
static float         _rightRamped   = 0.0f;

static unsigned long _lastInnerUs   = 0;
static unsigned long _lastOuterMs   = 0;

// ROS2 bridge state
static float         _linearMs      = 0.0f; // Latest linear_x  (m/s)
static float         _angularRads   = 0.0f; // Latest angular_z (rad/s)
static unsigned long _lastPacketMs  = 0;    // Timestamp of last valid packet

// Serial RX buffer — accumulates content between '<' and '>'
static constexpr int RX_BUF_SIZE = 32;
static char          _rxBuf[RX_BUF_SIZE];
static int           _rxIdx    = 0;
static bool          _rxActive = false;

// Heading lock for straight-line travel
static bool          _headingLocked = false;
static float         _lockedHeading = 0.0f;

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

// Clamp both RPM setpoints and store for the inner loop's slew-rate stage.
void setTargetRPM(float leftRPM, float rightRPM) {
    _leftSetpoint  = constrain(leftRPM,  -MAX_RPM, MAX_RPM);
    _rightSetpoint = constrain(rightRPM, -MAX_RPM, MAX_RPM);
}

// Move 'current' toward 'target' by at most 'maxStep' in one call.
static float applySlew(float current, float target, float maxStep) {
    return current + constrain(target - current, -maxStep, maxStep);
}

// Wrap angle to (−180, +180] — local copy since DriveSystem's version is private.
static float wrapAngle(float a) {
    while (a >  180.f) a -= 360.f;
    while (a < -180.f) a += 360.f;
    return a;
}

// =============================================================================
// OUTER LOOP — 20 Hz
// Runs differential-drive kinematics, Sync PID (L3), Heading PID (L4).
// Position PID (L2) is intentionally skipped: ROS2/Nav2 owns position.
// =============================================================================
static void applyVelocityCommand(float dt) {
    // ── Differential-drive kinematics: (linear_x, angular_z) → per-wheel m/s
    // v_L = linear_x − angular_z × (WHEEL_BASE / 2)
    // v_R = linear_x + angular_z × (WHEEL_BASE / 2)
    // WHEEL_BASE_M and WHEEL_CIRCUMF_M are defined in Config.h.
    const float v_left  = _linearMs - (_angularRads * WHEEL_BASE_M * 0.5f);
    const float v_right = _linearMs + (_angularRads * WHEEL_BASE_M * 0.5f);

    // Convert m/s → RPM:  RPM = (v / circumference) × 60
    float rpmLeft  = (v_left  / WHEEL_CIRCUMF_M) * 60.0f;
    float rpmRight = (v_right / WHEEL_CIRCUMF_M) * 60.0f;

    // ── Layer 3: Sync PID — correct encoder tick imbalance ───────────────────
    // Positive syncCorr means the left wheel is lagging: speed it up, slow right.
    const long  lCount   = leftCtrl.getEncoderCount();
    const long  rCount   = rightCtrl.getEncoderCount();
    const float syncCorr = drive.syncPID.compute(0.f, (float)(lCount - rCount), dt);

    // ── Layer 4: Heading PID — maintain heading during straight travel ────────
    // Heading PID is active only when angular_z ≈ 0 (straight travel).
    // During commanded rotation, ROS2 controls the turn; heading lock is released.
    float headCorr = 0.0f;
    if (fabsf(_angularRads) < 0.05f) {
        if (!_headingLocked) {
            _lockedHeading = drive.getHeadingDeg();
            _headingLocked = true;
            drive.headingPID.reset();
        }
        // Positive hErr = need clockwise correction = left faster, right slower.
        const float hErr = wrapAngle(_lockedHeading - drive.getHeadingDeg());
        headCorr = drive.headingPID.compute(hErr, 0.f, dt);
    } else {
        _headingLocked = false;
    }

    // ── Sum all outer corrections → setpoints for the inner Velocity PID ─────
    setTargetRPM(rpmLeft  + syncCorr + headCorr,
                 rpmRight - syncCorr - headCorr);
}

// =============================================================================
// INNER LOOP — 50 Hz
// Applies slew-rate limiter, then runs Velocity PID on both motor controllers.
// Uses micros() for more accurate timing than millis().
// =============================================================================
static void runInnerLoop() {
    const unsigned long now     = micros();
    const unsigned long elapsed = now - _lastInnerUs;
    if (elapsed < INNER_INTERVAL_US) return;
    _lastInnerUs = now;

    const float dt      = (float)elapsed * 1.0e-6f;
    const float maxStep = MAX_RPM_STEP_PER_SEC * dt;

    _leftRamped  = applySlew(_leftRamped,  _leftSetpoint,  maxStep);
    _rightRamped = applySlew(_rightRamped, _rightSetpoint, maxStep);

    // Feed slew-limited targets into each motor's Velocity PID (Layer 1)
    leftCtrl.setTargetRPM(_leftRamped);
    rightCtrl.setTargetRPM(_rightRamped);

    leftCtrl.update(dt);    // velPID.compute() → MotorDriver::setSpeed()
    rightCtrl.update(dt);
}

// =============================================================================
// OUTER LOOP — 20 Hz non-blocking wrapper
// =============================================================================
static void runOuterLoop() {
    const unsigned long now     = millis();
    const unsigned long elapsed = now - _lastOuterMs;
    if (elapsed < OUTER_INTERVAL_MS) return;
    _lastOuterMs = now;

    applyVelocityCommand((float)elapsed * 1.0e-3f);
}

// =============================================================================
// ROS2 SERIAL BRIDGE
// =============================================================================

// Called when a complete '<...>' packet is ready. Stores the parsed velocity
// command and resets the watchdog timer.
static void parsePacket(const char* buf) {
    float linear_x, angular_z;
    if (sscanf(buf, "%f,%f", &linear_x, &angular_z) != 2) return;
    _linearMs     = linear_x;
    _angularRads  = angular_z;
    _lastPacketMs = millis();
}

// Drain Serial one byte at a time. Accumulates content between '<' and '>'.
// Never blocks — safe to call on every loop() iteration.
static void readSerial() {
    while (Serial.available()) {
        const char c = (char)Serial.read();
        if (c == '<') {
            _rxIdx = 0; _rxActive = true;
        } else if (c == '>' && _rxActive) {
            _rxBuf[_rxIdx] = '\0';
            _rxActive = false;
            parsePacket(_rxBuf);
        } else if (_rxActive && _rxIdx < RX_BUF_SIZE - 1) {
            _rxBuf[_rxIdx++] = c;
        }
        // Characters outside '<…>' are silently discarded
    }
}

// Safety: if no valid packet in WATCHDOG_MS, zero the velocity command.
// The slew-rate limiter then decelerates the motors gradually.
static void checkWatchdog() {
    if (millis() - _lastPacketMs > WATCHDOG_MS) {
        _linearMs = 0.0f; _angularRads = 0.0f;
        setTargetRPM(0.0f, 0.0f);
    }
}

// Send odometry to the ROS2 bridge node at 20 Hz.
// Format: [L_ticks,R_ticks,L_rpm,R_rpm]
// The ROS2 parser filters for lines starting with '['; debug text is ignored.
static void sendOdometry() {
    static unsigned long lastOdomMs = 0;
    const unsigned long  now        = millis();
    if (now - lastOdomMs < ODOM_MS) return;
    lastOdomMs = now;

    Serial.print('[');
    Serial.print(leftCtrl.getEncoderCount());   Serial.print(',');
    Serial.print(rightCtrl.getEncoderCount());  Serial.print(',');
    Serial.print(leftCtrl.getActualRPM(),  2);  Serial.print(',');
    Serial.print(rightCtrl.getActualRPM(), 2);
    Serial.println(']');
}

// =============================================================================
void setup() {
    Serial.begin(115200);
    Serial.println("=== AMR Firmware: 4-Layer Cascade PID + ROS2 Bridge ===");

    // Override Layer 1 (Velocity PID) defaults with the constants at the top.
    // velPID is public in MotorController.h to allow this.
    leftCtrl.velPID.setGains(VEL_KP, VEL_KI, VEL_KD);
    rightCtrl.velPID.setGains(VEL_KP, VEL_KI, VEL_KD);

    // DriveSystem::begin() initialises both motor controllers and the BNO055.
    // It also latches the boot heading so headingPID starts with zero error.
    if (!drive.begin()) {
        Serial.println("FATAL: BNO055 not found. Check I2C wiring (SDA=18, SCL=19). Halting.");
        while (true) {}
    }

    Serial.print("Layer 1 — Vel PID:  Kp="); Serial.print(VEL_KP);
    Serial.print("  Ki="); Serial.print(VEL_KI);
    Serial.print("  Kd="); Serial.println(VEL_KD);
    Serial.print("Slew rate: "); Serial.print(MAX_RPM_STEP_PER_SEC);
    Serial.println(" RPM/s");
    Serial.println("Layer 3 — Sync PID: Kp=0.25 (default, tune after Vel PID)");
    Serial.println("Layer 4 — Head PID: Kp=1.50 (default, tune after Sync PID)");
    Serial.println("Ready. Waiting for ROS2 <linear_x,angular_z> packets...");

    _lastInnerUs  = micros();
    _lastOuterMs  = millis();
    _lastPacketMs = millis(); // Prevent watchdog from firing before first packet
}

// =============================================================================
void loop() {
    readSerial();       // Drain UART; parse <lin,ang> packets → _linearMs/_angularRads
    checkWatchdog();    // Zero velocity command if no packet received in 500 ms
    runOuterLoop();     // 20 Hz: kinematics + Sync PID + Heading PID → setTargetRPM()
    runInnerLoop();     // 50 Hz: slew rate + Velocity PID → PWM via BTS7960
    sendOdometry();     // 20 Hz: [L_ticks,R_ticks,L_rpm,R_rpm] → Serial → ROS2
}
