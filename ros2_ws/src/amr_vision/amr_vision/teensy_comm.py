"""
teensy_comm.py
--------------
Serial communication between the Jetson (vision) and the Teensy 4.1 (robot control).

All commands are sent as plain ASCII strings terminated with newline.
The Teensy firmware reads these strings and executes the appropriate action.

Command protocol (agree this with your teammates who write the Teensy firmware):

    LIFT_UP\n              — raise scissor lift to pre-programmed shelf height
    APPROACH:<mm>\n        — drive robot forward until distance to box = <mm>
    SERVO:<value>\n        — lateral correction (positive=right, negative=left)
    GRIP\n                 — activate suction cup
    STOP\n                 — emergency stop all motion

Example:
    APPROACH:450\n   → drive forward until box is 450mm away
    SERVO:0.0240\n   → nudge robot right
    SERVO:-0.0180\n  → nudge robot left
    GRIP\n           → cup on

dry_run mode:
    When dry_run=True, commands are printed to console instead of sent over serial.
    Use this for testing the vision pipeline without the physical robot.

Windows port names:  "COM3", "COM4", etc.
Jetson/Linux names:  "/dev/ttyACM0", "/dev/ttyUSB0", etc.
"""

import time
import serial
import serial.tools.list_ports

BAUD_RATE    = 115200   # must match the Teensy firmware
SEND_TIMEOUT = 0.05     # seconds — how long to wait for each write


def list_available_ports() -> list[str]:
    """Utility: print all available serial ports (helpful for finding the Teensy)."""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]


class TeensyComm:
    """
    Serial communication wrapper for the Teensy 4.1.

    Usage:
        teensy = TeensyComm(port="COM3")
        teensy.send_lift_up()
        teensy.send_approach(450)
        teensy.send_servo(0.024)
        teensy.send_grip()
        teensy.close()
    """

    def __init__(self, port: str = "COM3", baud: int = BAUD_RATE,
                 dry_run: bool = False):
        """
        port:    serial port name ("COM3" on Windows, "/dev/ttyACM0" on Jetson)
        baud:    baud rate (must match Teensy firmware)
        dry_run: if True, print commands instead of sending over serial
        """
        self._dry_run = dry_run
        self._serial  = None

        if not dry_run:
            try:
                self._serial = serial.Serial(port, baud, timeout=SEND_TIMEOUT)
                time.sleep(0.1)  # short pause — Teensy resets on serial open
                print(f"[TeensyComm] Connected on {port} @ {baud} baud")
            except serial.SerialException as e:
                print(f"[TeensyComm] WARNING: Cannot open {port}: {e}")
                print(f"[TeensyComm] Available ports: {list_available_ports()}")
                print("[TeensyComm] Falling back to dry_run mode.")
                self._dry_run = True
        else:
            print(f"[TeensyComm] dry_run mode — commands will be printed, not sent")

    def send_lift_up(self):
        """
        Tell Teensy to raise the scissor lift to the pre-programmed shelf height.
        The target height comes from the order system, not from vision.
        """
        self._send("LIFT_UP")

    def send_approach(self, distance_mm: int):
        """
        Tell Teensy to drive the robot forward until the box is <distance_mm> away.
        The Teensy uses its own distance sensor or encoder to stop at the right point.

        Args:
            distance_mm: measured depth from the Astra Pro to the box face
        """
        self._send(f"APPROACH:{distance_mm}")

    def send_servo(self, correction: float):
        """
        Send a lateral alignment correction.
        Positive = move robot right, negative = move robot left.
        Magnitude is proportional to pixel error × Kp.

        The Teensy firmware interprets this as a brief wheel velocity difference.

        Args:
            correction: float from VisualServo.update() — e.g. 0.0240 or -0.0180
        """
        # Round to 4 decimal places — sufficient precision, avoids floating point noise
        self._send(f"SERVO:{correction:.4f}")

    def send_grip(self):
        """Activate the suction cup. Robot must be aligned before calling this."""
        self._send("GRIP")

    def send_stop(self):
        """Emergency stop all robot motion."""
        self._send("STOP")

    def close(self):
        """Release the serial port cleanly."""
        if self._serial and self._serial.is_open:
            self.send_stop()
            self._serial.close()
            print("[TeensyComm] Port closed.")

    def _send(self, command: str):
        """
        Internal: append newline and send command.
        In dry_run mode, prints to console instead.
        """
        message = command + "\n"
        if self._dry_run:
            print(f"[TeensyComm DRY-RUN] >> {command}")
            return
        try:
            self._serial.write(message.encode("ascii"))
            self._serial.flush()
        except serial.SerialException as e:
            print(f"[TeensyComm] Send failed: {e}")

    # Context manager support
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── Standalone test ────────────────────────────────────────────────────────────
# Run:  python amr_vision/teensy_comm.py
# Sends a sequence of test commands in dry_run mode.
if __name__ == "__main__":
    print("TeensyComm test — dry_run (no serial hardware needed)")
    print("Available ports:", list_available_ports())

    with TeensyComm(port="COM3", dry_run=True) as t:
        print("\nSimulating one full pick sequence:")
        t.send_lift_up()
        time.sleep(0.5)
        t.send_approach(450)
        time.sleep(0.5)
        t.send_servo(0.0240)
        time.sleep(0.1)
        t.send_servo(0.0080)
        time.sleep(0.1)
        t.send_servo(-0.0020)
        time.sleep(0.1)
        t.send_grip()
        print("\nSequence complete.")
