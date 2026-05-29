// Teensy 4.1 — Serial bridge: receives velocity commands from the ROS 2
// serial_bridge_node and forwards them to the motor driver.
//
// Expected packet format (sent by the Pi):  <linear_x,angular_z>\n
// Example:                                   <0.2500,-0.1000>
//
// Teammate: insert your PWM / direction logic inside applyMotorSpeeds().

// ── Tuneable constants ───────────────────────────────────────────────────────
static constexpr uint32_t SERIAL_BAUD      = 115200;
static constexpr uint16_t PACKET_BUF_SIZE  = 64;
// If no packet arrives within this many ms, send a stop command.
static constexpr uint32_t WATCHDOG_MS      = 500;

// ── State ────────────────────────────────────────────────────────────────────
static char    packetBuf[PACKET_BUF_SIZE];
static uint8_t bufIdx      = 0;
static bool    inPacket    = false;
static uint32_t lastPacketMs = 0;

// ── Prototype ────────────────────────────────────────────────────────────────
void applyMotorSpeeds(float linear, float angular);

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(SERIAL_BAUD);  // USB-serial (also /dev/ttyACM0 on the Pi side)
    while (!Serial && millis() < 3000) {}  // wait for USB enumeration (max 3 s)
}

// ── Main loop ────────────────────────────────────────────────────────────────
void loop() {
    // --- read incoming bytes one at a time ---------------------------------
    while (Serial.available()) {
        char c = Serial.read();

        if (c == '<') {
            // start-of-packet marker: reset buffer
            bufIdx   = 0;
            inPacket = true;
            continue;
        }

        if (!inPacket) continue;  // ignore bytes before first '<'

        if (c == '>') {
            // end-of-packet marker: null-terminate and parse
            packetBuf[bufIdx] = '\0';
            inPacket          = false;

            float linear  = 0.0f;
            float angular = 0.0f;

            // sscanf returns the number of fields successfully parsed
            if (sscanf(packetBuf, "%f,%f", &linear, &angular) == 2) {
                lastPacketMs = millis();
                applyMotorSpeeds(linear, angular);
            }
            // malformed packet — silently discard
            continue;
        }

        // accumulate packet body; drop oversized packets
        if (bufIdx < PACKET_BUF_SIZE - 1) {
            packetBuf[bufIdx++] = c;
        } else {
            inPacket = false;  // overrun — discard until next '<'
        }
    }

    // --- watchdog: stop motors if comms are lost ---------------------------
    if ((millis() - lastPacketMs) > WATCHDOG_MS) {
        applyMotorSpeeds(0.0f, 0.0f);
    }
}

// ── Motor output ─────────────────────────────────────────────────────────────
// TODO (teammate): replace this stub with your PWM / direction-pin logic.
//
// linear  — forward/backward velocity in m/s  (positive = forward)
// angular — rotational velocity in rad/s      (positive = counter-clockwise)
void applyMotorSpeeds(float linear, float angular) {
    (void)linear;   // suppress unused-variable warning until implemented
    (void)angular;
}
