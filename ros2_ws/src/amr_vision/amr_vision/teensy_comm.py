"""
teensy_comm.py — vision → robot command transport (ROS 2 version)

No longer opens a serial port. Publishes std_msgs/String to /aux/command,
which serial_bridge_node (the single serial owner) forwards to the Teensy.
Public API is unchanged so the rest of the vision pipeline is untouched.

Why this changed:
    On the integrated robot only ONE program may open the serial port
    (serial_bridge_node, which drives the wheels). Vision used to open
    COM3 / /dev/ttyACM0 directly, which (a) collided with the bridge and
    (b) hard-wired the code to one machine's port, making the Jetson move
    painful. Publishing a ROS string instead means the same code runs on
    the PC and the Jetson unchanged.

dry_run mode:
    When dry_run=True, commands are printed to console instead of published.
    Use this to run vision_main.py as a plain PC test script (no ROS graph).
"""

from std_msgs.msg import String


class TeensyComm:
    def __init__(self, node=None, port: str = "", baud: int = 0, dry_run: bool = False):
        """
        node:    an rclpy Node to publish through (pass your vision node's self).
                 If None and not dry_run, a private node is created.
        port/baud: accepted but ignored — kept so old call sites don't break.
        dry_run: if True, print commands instead of publishing.
        """
        self._dry_run = dry_run
        self._pub = None
        if dry_run:
            print("[TeensyComm] dry_run — commands printed, not published")
            return

        if node is None:
            import rclpy
            from rclpy.node import Node
            if not rclpy.ok():
                rclpy.init()
            node = Node("teensy_comm")
        self._pub = node.create_publisher(String, "/aux/command", 10)
        print("[TeensyComm] publishing to /aux/command")

    # ── Only SERVO is still vision's job; the rest are coordinator-owned now ──
    def send_servo(self, correction: float):
        self._send(f"SERVO {correction:.4f}")

    def send_stop(self):
        self._send("STOP")

    # Kept for backward compatibility / manual bring-up, but the coordinator
    # normally issues these. They map onto the shared wire protocol:
    def send_lift_up(self, mm: int = 200): self._send(f"LIFT {mm}")
    def send_approach(self, distance_mm: int): self._send(f"APPROACH {distance_mm}")
    def send_grip(self): self._send("PUMP ON")

    def close(self):
        pass  # nothing to release — no serial handle

    def _send(self, command: str):
        if self._dry_run:
            print(f"[TeensyComm DRY-RUN] >> {command}")
            return
        self._pub.publish(String(data=command))

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
