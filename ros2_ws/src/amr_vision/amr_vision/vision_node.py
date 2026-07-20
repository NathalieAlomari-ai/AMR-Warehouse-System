"""
vision_node.py
--------------
ROS 2 wrapper around the vision pipeline (integration version).

In the integrated robot the mission COORDINATOR owns the pick sequence
(drive-to-shelf, lift, approach, grip, drop-off). Vision is no longer a
self-driving state machine — it is a *service* the coordinator queries:

    Coordinator -> vision   on /vision/request  (std_msgs/String):  "SHELF_QR" | "BOX_QR"
    vision -> Coordinator   on /vision/result   (std_msgs/String):  "OK <sku>" | "FAIL"

  SHELF_QR : read/confirm the shelf QR, reply "OK <id>" or "FAIL".
  BOX_QR   : confirm the box QR AND centre the suction cup, then reply "OK <sku>".

Centring the cup = moving the ROBOT so the fixed suction cup lines up with the
box. There is NO cup servo motor, so the correction becomes wheel motion: we
publish geometry_msgs/Twist to /cmd_vel (which serial_bridge_node turns into
wheel RPM). A differential drive can't strafe, so horizontal centring is a
small in-place rotation (Twist.angular.z). Nav2 has already reached the shelf
and gone idle before BOX_QR runs, so nothing else drives /cmd_vel meanwhile.

  NOTE: vision does NOT publish to /aux/command and never opens serial. LIFT /
  STEP / PUMP / STOP are the coordinator's job; robot motion goes via /cmd_vel.

Design: blocking request handler. The /vision/request callback grabs frames
from the (already-open) camera and runs the detect/centre loop to completion
before replying. Detector code (YOLO / QRDetector / BoxDetector / VisualServo /
DepthSampler) is reused unchanged.

vision_main.py is kept as-is for standalone PC testing (run it with --dry-run).

Run (once registered in setup.py):
    ros2 run amr_vision vision_node
Pretend to be the coordinator:
    ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'SHELF_QR'}"
    ros2 topic echo /vision/result
    ros2 topic echo /cmd_vel                 # watch the centring rotation
"""

import os
import sys
import time

# ── Import shim ──────────────────────────────────────────────────────────────
# The sibling modules (config, camera_utils, qr_detector, ...) use flat, bare
# imports of each other (script style). Under `ros2 run` this file is imported
# as amr_vision.vision_node, so those bare imports would not resolve. Putting
# this file's own directory on sys.path makes the flat imports work BOTH under
# ros2 run and when running the standalone test scripts directly — without
# having to touch the other five modules.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist
from ultralytics import YOLO

from config        import SHOW_WINDOW as _DEFAULT_SHOW, SERVO_SEND_HZ
from camera_utils  import AstraCamera
from qr_detector   import QRDetector
from box_detector  import BoxDetector
from visual_servo  import VisualServo

# ── CONFIG ────────────────────────────────────────────────────────────────────
def _resolve_model_path() -> Path:
    """Locate best.pt whether run as a plain script, via `ros2 run` with a
    --symlink-install build, or via a plain colcon build (where __file__ lives
    under build/ or install/, not the source tree). Override with AMR_MODEL_PATH."""
    env = os.getenv("AMR_MODEL_PATH")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve()            # resolve() follows symlink-install
    local = here.parent.parent / "models" / "best.pt"
    if local.is_file():
        return local
    # Plain colcon build: walk up and find the source checkout's models/best.pt.
    for parent in here.parents:
        cand = parent / "src" / "amr_vision" / "models" / "best.pt"
        if cand.is_file():
            return cand
    return local   # not found — return the expected path for a clear error

MODEL_PATH = _resolve_model_path()

# A decoded QR value must repeat this many consecutive frames before we trust it.
# Replaces QRDetector's expected_id confirmation — we report the value we read,
# the coordinator decides whether it is the right shelf/SKU.
STABLE_READ_FRAMES = 5

# Consecutive aligned frames required before we call the cup "centred".
ALIGN_STABLE_FRAMES = 10

# Per-request timeouts (seconds). If exceeded, reply FAIL so the coordinator
# is never left waiting forever.
#
# IMPORTANT: these MUST stay comfortably under the coordinator's `vision_timeout`
# (default 30.0 s), which it applies to BOTH SHELF_QR and BOX_QR. For BOX_QR the
# coordinator waits ONE timeout for read+centre combined, so BOX_QR_TIMEOUT +
# CENTER_TIMEOUT must be < 30 s or the coordinator aborts mid-centre. If real-world
# centring needs longer, raise the coordinator's `vision_timeout` param to match.
SHELF_QR_TIMEOUT = 25.0   # < coordinator vision_timeout (30 s)
BOX_QR_TIMEOUT   = 10.0   # to read the box QR
CENTER_TIMEOUT   = 15.0   # to centre the cup  (10 + 15 = 25 s < 30 s)

# Max in-place rotation speed while centring (rad/s). Caps the VisualServo
# correction so a large pixel offset can't spin the robot dangerously fast.
MAX_TURN_RATE = 0.5

# Smoothness: exponentially smooth the anchor pixel position across frames so
# per-frame YOLO/QR bbox jitter doesn't produce jerky rotation. 1.0 = react
# instantly (no smoothing), lower = smoother but laggier. 0.5 is a good start.
# (serial_bridge_node ALSO ramps angular velocity at max_angular_accel, so the
#  wheels are smoothed a second time downstream.)
ANCHOR_SMOOTHING = 0.5

# Minimum |angular.z| that actually overcomes wheel stiction (rad/s). Below this,
# a tiny correction stalls the wheels, error builds, then the robot lurches.
# A small floor keeps the final approach continuous. 0.0 = disabled (tune on robot).
MIN_TURN_RATE = 0.0

# Set True if the robot rotates the WRONG way while centring (hardware sign flip).
INVERT_TURN = False

SHOW_WINDOW = _DEFAULT_SHOW
# ─────────────────────────────────────────────────────────────────────────────


class VisionNode(Node):
    """ROS 2 vision service. See module docstring for the request/response contract."""

    def __init__(self):
        super().__init__("vision_node")

        self.get_logger().info(f"Loading model: {MODEL_PATH}")
        self._model = YOLO(str(MODEL_PATH))

        # expected_id="" — we use these detectors only to LOCATE and DECODE the QR
        # (result.found / .bbox / .decoded). Match/confirm is not used here.
        self._qr     = QRDetector(self._model, expected_id="")
        self._box    = BoxDetector(self._model)
        self._servo  = VisualServo()

        # Robot motion for cup centring. On the real robot twist_mux OWNS /cmd_vel
        # (it merges cmd_vel_nav prio 10 + cmd_vel_joy prio 100). Publishing straight
        # to /cmd_vel makes vision a SECOND publisher that fights Nav2 — the robot
        # then obeys Nav2's residual/recovery motion (e.g. driving backwards) instead
        # of our rotation. So by default we publish to cmd_vel_vision, which twist_mux
        # merges at priority 50 (beats nav, yields to the joystick e-stop).
        #
        #   With twist_mux (real robot):  cmd_vel_topic = /cmd_vel_vision  (default)
        #   Standalone, no twist_mux   :  --ros-args -p cmd_vel_topic:=/cmd_vel
        self._cmd_vel_topic = self.declare_parameter(
            "cmd_vel_topic", "/cmd_vel_vision"
        ).get_parameter_value().string_value
        self._cmd_vel_pub = self.create_publisher(Twist, self._cmd_vel_topic, 10)
        self.get_logger().info(f"centring will publish to: {self._cmd_vel_topic}")

        # Camera stays open for the node's lifetime; handlers grab frames on demand.
        self.get_logger().info("Opening camera...")
        self._cam = AstraCamera()

        self.create_subscription(String, "/vision/request", self._on_request, 10)
        self._result_pub = self.create_publisher(String, "/vision/result", 10)
        self.get_logger().info("Ready — waiting on /vision/request (SHELF_QR | BOX_QR)")

    # ── Request dispatch ─────────────────────────────────────────────────────────
    def _on_request(self, msg):
        req = msg.data.strip()
        self.get_logger().info(f"request: {req}")

        if req == "SHELF_QR":
            sku = self.detect_shelf_qr()
            self._reply(f"OK {sku}" if sku else "FAIL")

        elif req == "BOX_QR":
            sku = self.detect_box_qr()
            if not sku:
                self._reply("FAIL")     # STOP is the coordinator's job, not vision's
                return
            if self.center_cup_with_servo():
                self._reply(f"OK {sku}")
            else:
                self._reply("FAIL")

        else:
            self.get_logger().warn(f"unknown request '{req}' — replying FAIL")
            self._reply("FAIL")

    def _reply(self, text):
        self.get_logger().info(f"result: {text}")
        self._result_pub.publish(String(data=text))

    # ── Detection helpers (reuse the existing detectors) ─────────────────────────
    def detect_shelf_qr(self) -> str | None:
        """Read the shelf QR. Returns the decoded id (stable read) or None on timeout."""
        return self._read_qr_stable(SHELF_QR_TIMEOUT, tag="SHELF")

    def detect_box_qr(self) -> str | None:
        """Read the box QR. Returns the decoded SKU (stable read) or None on timeout."""
        return self._read_qr_stable(BOX_QR_TIMEOUT, tag="BOX")

    def _read_qr_stable(self, timeout: float, tag: str) -> str | None:
        """Grab frames until the same non-empty QR value is decoded STABLE_READ_FRAMES
        times in a row, or until timeout."""
        self._qr.reset()
        last_val, streak = "", 0
        deadline = time.time() + timeout

        while time.time() < deadline:
            ok, rgb, _ = self._cam.read()
            if not ok or rgb is None or rgb.ndim != 3 or rgb.shape[2] != 3:
                continue

            res = self._qr.detect(rgb)
            val = res.decoded if (res.found and res.decoded) else ""

            if val and val == last_val:
                streak += 1
            else:
                last_val, streak = val, (1 if val else 0)

            self._maybe_show(rgb, f"{tag}_QR read '{val}' {streak}/{STABLE_READ_FRAMES}")

            if streak >= STABLE_READ_FRAMES:
                self.get_logger().info(f"{tag} QR confirmed: '{val}'")
                return val

        self.get_logger().warn(f"{tag} QR read timed out after {timeout:.0f}s")
        return None

    def center_cup_with_servo(self) -> bool:
        """Two-phase visual centring (COARSE box centre -> FINE QR centre). Rotates the
        robot in place via /cmd_vel until the box is centred, then stops. Returns True
        once the cup holds alignment for ALIGN_STABLE_FRAMES frames, False on timeout.

        This is the Stage-3 loop from vision_main.py, but the correction now drives
        Twist.angular.z on /cmd_vel instead of a SERVO string, and there is no GRIP
        handoff (grip is the coordinator's job now)."""
        self._servo.reset()
        align_count     = 0
        last_cmd_send   = 0.0
        cmd_interval    = 1.0 / SERVO_SEND_HZ
        deadline        = time.time() + CENTER_TIMEOUT
        anchor_ema      = None    # smoothed anchor pixel (EMA), see ANCHOR_SMOOTHING

        while time.time() < deadline:
            ok, rgb, depth = self._cam.read()
            if not ok or rgb is None or rgb.ndim != 3 or rgb.shape[2] != 3:
                continue
            w = rgb.shape[1]

            # FINE anchor: box QR centre (precise). COARSE fallback: box centre.
            qr_result = self._qr.detect(rgb)
            qr_cx = None
            if qr_result.found and qr_result.bbox is not None:
                qx1, _, qx2, _ = qr_result.bbox
                qr_cx = (qx1 + qx2) // 2

            box_result = self._box.detect(rgb, depth)
            box_cx = box_result.center[0] if box_result.found else None

            if qr_cx is not None:
                anchor_cx, mode = qr_cx, "FINE (QR)"
            elif box_cx is not None:
                anchor_cx, mode = box_cx, "COARSE (box)"
            else:
                # Nothing to aim at — stop rotating and keep looking.
                self._stop_robot()
                self._maybe_show(rgb, "centre: nothing detected")
                continue

            # Smooth the anchor to kill per-frame detection jitter → smoother turn.
            # (Also smooths the COARSE→FINE handoff, so switching from box centre
            #  to QR centre doesn't snap the command.)
            if anchor_ema is None:
                anchor_ema = float(anchor_cx)
            else:
                anchor_ema = (ANCHOR_SMOOTHING * anchor_cx
                              + (1.0 - ANCHOR_SMOOTHING) * anchor_ema)

            correction, offset_px, aligned = self._servo.update(int(round(anchor_ema)), w)
            now = time.time()

            if aligned:
                align_count += 1
                if align_count == 1:          # stop once on entering aligned
                    self._stop_robot()
            else:
                align_count = 0
                if now - last_cmd_send >= cmd_interval:   # rate-limit to SERVO_SEND_HZ
                    self._turn_robot(correction)
                    last_cmd_send = now

            self._maybe_show(
                rgb,
                f"{mode} off={offset_px:+d}px corr={correction:+.4f} "
                f"stable={align_count}/{ALIGN_STABLE_FRAMES}")

            # Require a stable FINE (QR-anchored) lock before declaring centred.
            if align_count >= ALIGN_STABLE_FRAMES and qr_cx is not None:
                self.get_logger().info(f"cup centred (offset={offset_px}px)")
                self._stop_robot()
                return True

        self.get_logger().warn(f"cup centring timed out after {CENTER_TIMEOUT:.0f}s")
        self._stop_robot()
        return False

    # ── Robot motion (via /cmd_vel) ──────────────────────────────────────────────
    def _turn_robot(self, correction: float):
        """Rotate in place to bring the box toward frame centre.

        VisualServo returns a positive correction when the box is RIGHT of centre;
        in ROS a positive angular.z turns LEFT, so we negate to turn toward the box.
        Flip INVERT_TURN if the hardware rotates the wrong way. Magnitude is the
        VisualServo Kp*offset value, clamped to MAX_TURN_RATE."""
        wz = -correction
        if INVERT_TURN:
            wz = -wz
        # Stiction floor: keep small non-zero corrections above the wheels'
        # dead-band so the final approach stays continuous instead of lurching.
        if 0.0 < abs(wz) < MIN_TURN_RATE:
            wz = MIN_TURN_RATE if wz > 0 else -MIN_TURN_RATE
        wz = max(-MAX_TURN_RATE, min(MAX_TURN_RATE, wz))
        t = Twist()
        t.angular.z = float(wz)
        self._cmd_vel_pub.publish(t)

    def _stop_robot(self):
        """Publish a zero Twist. serial_bridge HOLDS the last /cmd_vel target, so an
        explicit zero is required to actually stop the rotation."""
        self._cmd_vel_pub.publish(Twist())

    # ── Display (optional; off on headless Jetson) ───────────────────────────────
    def _maybe_show(self, frame, label: str):
        if not SHOW_WINDOW:
            return
        import cv2
        cv2.putText(frame, label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imshow("AMR Vision Node", frame)
        cv2.waitKey(1)

    # ── Cleanup ──────────────────────────────────────────────────────────────────
    def destroy_node(self):
        try:
            self._stop_robot()      # never leave the robot rotating on shutdown
            self._cam.close()
        except Exception:
            pass
        if SHOW_WINDOW:
            import cv2
            cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
