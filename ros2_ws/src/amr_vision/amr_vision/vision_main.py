"""
vision_main.py
--------------
The main vision pipeline state machine.

This file is the ONLY file your robot's main process should import and run.
It coordinates all 3 stages in order:

  STAGE_1: QR confirmation
    Camera detects QR on the lower part of the shelf.
    Decoded content is compared to the expected shelf ID.
    On confirmation -> signal navigation to raise scissor lift.

  STAGE_2: Barcode confirmation + depth measurement
    Scissor lift has reached target height.
    Camera detects barcode on the box and confirms the SKU.
    Depth is measured to determine how far the robot must approach.
    On confirmation -> send approach distance to Teensy.

  STAGE_3: Visual servo alignment (two-phase)
    Robot drives forward to approach distance (Teensy handles that).
    COARSE phase: box centre used for servo — box is large, always visible.
    FINE phase:   barcode centre used once offset < 40px — more precise.
    When barcode offset < 10px -> send suction cup activation command.

  DONE: Task complete. Wait for next order.
  ERROR: Something was wrong (wrong shelf, wrong SKU, timeout).

How to run:
    python amr_vision/vision_main.py --shelf SHELF-A3 --sku 123456789

For integration with ROS2 or MQTT, replace the print() calls
with your team's message publisher.
"""

import cv2
import time
import argparse
import numpy as np
from enum import Enum, auto
from pathlib import Path
from ultralytics import YOLO

from config          import TEENSY_PORT, SHOW_WINDOW as _DEFAULT_SHOW, SERVO_SEND_HZ
from camera_utils    import AstraCamera
from qr_detector     import QRDetector, draw_qr_overlay
from box_detector    import BoxDetector, draw_box_overlay
from visual_servo    import VisualServo, draw_servo_overlay, ALIGN_EXIT_PX
from depth_utils     import DepthSampler
from teensy_comm     import TeensyComm
from mqtt_publisher  import AMRMqttPublisher

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_PATH = Path(__file__).parent.parent / "models" / "best.pt"

# Timeout per stage (seconds). If a stage takes longer, move to ERROR.
STAGE_TIMEOUT = {
    "STAGE_1": 30,   # 30 s to find and confirm QR
    "STAGE_2": 20,   # 20 s to confirm barcode + measure depth after lift rises
    "STAGE_3": 15,   # 15 s to align after approach
}

# After alignment, send the grip command, then wait this long before DONE.
GRIP_DELAY_S = 1.5

# Consecutive aligned frames required before sending GRIP.
# Prevents gripping while the robot is still settling after a PID correction.
# At ~20 fps this is ~0.5 s of confirmed stillness before the cup activates.
ALIGN_STABLE_FRAMES = 10

# If the robot drifts more than this during the grip phase, print a warning.
GRIP_DRIFT_WARN_PX = 20

# Whether to show the live camera window.
# Auto-set by config.py: True on Windows, False on headless Jetson.
# Override: SHOW_WINDOW=1 python vision_main.py ...
SHOW_WINDOW = _DEFAULT_SHOW
# ─────────────────────────────────────────────────────────────────────────────


class State(Enum):
    STAGE_1 = auto()   # QR confirmation
    STAGE_2 = auto()   # Barcode + depth
    STAGE_3 = auto()   # Visual servo alignment
    GRIPPING = auto()  # Suction cup activating
    DONE    = auto()   # Pick complete
    ERROR   = auto()   # Something went wrong


class VisionPipeline:
    """
    Orchestrates the full 3-stage vision pipeline for one pick operation.

    Usage:
        pipeline = VisionPipeline(shelf_id="SHELF-A3", expected_sku="123456789")
        pipeline.run()   # blocks until DONE or ERROR
    """

    def __init__(self, shelf_id: str, expected_sku: str,
                 teensy_port: str = TEENSY_PORT, dry_run: bool = False,
                 no_timeout: bool = False, mqtt_host: str = "localhost"):
        """
        shelf_id:     expected content of the QR code on the shelf
        expected_sku: expected barcode value on the target box
        teensy_port:  serial port of the Teensy 4.1
        dry_run:      if True, skip serial communication (useful for testing without robot)
        """
        self._shelf_id    = shelf_id
        self._expected_sku = expected_sku
        self._dry_run     = dry_run

        print(f"[VisionPipeline] Loading model: {MODEL_PATH}")
        self._model = YOLO(str(MODEL_PATH))

        # Two separate QR detectors: one for the shelf label (Stage 1),
        # one for the QR sticker on the box (Stage 2 + Stage 3 FINE).
        self._shelf_qr = QRDetector(self._model, expected_id=shelf_id)
        self._box_qr   = QRDetector(self._model, expected_id=expected_sku)
        self._s2_depth = DepthSampler()          # depth at box QR centre (Stage 2)

        self._box    = BoxDetector(self._model)  # coarse servo anchor (Stage 3)
        self._servo  = VisualServo()
        self._teensy = TeensyComm(port=teensy_port, dry_run=dry_run)
        self._mqtt   = AMRMqttPublisher(broker_host=mqtt_host,
                                        shelf_id=shelf_id,
                                        dry_run=dry_run)

        self._no_timeout      = no_timeout
        self._state           = State.STAGE_1
        self._stage_start     = time.time()
        self._grip_start      = None
        self._align_count     = 0      # consecutive aligned frames (Stage 3 stability gate)
        self._last_servo_send = 0.0    # timestamp of last SERVO command (rate limiter)

    def run(self):
        """
        Main loop. Opens camera, processes frames, transitions states.
        Blocks until the pick is complete (DONE) or fails (ERROR).
        """
        self._mqtt.publish_status("RUNNING")
        self._mqtt.publish_stage(self._state.name)

        with AstraCamera() as cam:
            print(f"[VisionPipeline] Camera open. Starting in state: {self._state.name}")

            while self._state not in (State.DONE, State.ERROR):
                ok, rgb, depth = cam.read()
                if not ok:
                    self._fail("Camera read failed")
                    break

                # Skip bad frames (Astra Pro can glitch occasionally)
                if rgb is None or rgb.ndim != 3 or rgb.shape[2] != 3:
                    print(f"[VisionPipeline] Bad frame shape, skipping")
                    continue

                # Check stage timeout
                if self._timed_out():
                    self._fail(f"Timeout in {self._state.name}")
                    break

                # Route to the correct stage handler
                if self._state == State.STAGE_1:
                    self._run_stage1(rgb)
                elif self._state == State.STAGE_2:
                    self._run_stage2(rgb, depth)
                elif self._state == State.STAGE_3:
                    self._run_stage3(rgb, depth)
                elif self._state == State.GRIPPING:
                    self._run_gripping(rgb)

                if SHOW_WINDOW:
                    # Draw current state name in top-right corner
                    label = self._state.name
                    cv2.putText(rgb, label,
                                (rgb.shape[1] - 160, 25),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                    cv2.imshow("AMR Vision Pipeline (Q=abort)", rgb)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        self._fail("User aborted")
                        break

        if SHOW_WINDOW:
            cv2.destroyAllWindows()
        self._teensy.close()
        self._mqtt.close()

        print(f"[VisionPipeline] Final state: {self._state.name}")
        return self._state == State.DONE

    # ── Stage handlers ─────────────────────────────────────────────────────────

    def _run_stage1(self, frame):
        """Stage 1: find and confirm QR code on shelf."""
        result = self._shelf_qr.detect(frame)
        if SHOW_WINDOW:
            draw_qr_overlay(frame, result)

        if result.confirmed:
            print(f"[Stage 1] QR confirmed: '{result.decoded}' -> signalling lift UP")
            self._teensy.send_lift_up()
            self._mqtt.publish_shelf_confirmed(result.decoded)
            self._transition(State.STAGE_2)

    def _run_stage2(self, frame, depth):
        """Stage 2: confirm box QR (SKU) and measure approach distance."""
        result = self._box_qr.detect(frame)
        if SHOW_WINDOW:
            draw_qr_overlay(frame, result)

        if result.confirmed:
            # Sample depth at the QR code centre
            x1, y1, x2, y2 = result.bbox
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            h, w = frame.shape[:2]
            cx = int(np.clip(cx, 0, w - 1))
            cy = int(np.clip(cy, 0, h - 1))
            distance_mm = self._s2_depth.get(depth, cx, cy)

            if distance_mm > 0:
                print(f"[Stage 2] QR confirmed: '{result.decoded}'  "
                      f"distance: {distance_mm} mm")
                self._teensy.send_approach(distance_mm)
                self._mqtt.publish_sku_confirmed(result.decoded, distance_mm)
                self._transition(State.STAGE_3)
            else:
                print("[Stage 2] QR confirmed, waiting for valid depth...")

    def _run_stage3(self, frame, depth):
        """
        Stage 3: two-phase visual servo alignment.

        FINE phase   — QR code on box face used as precise servo anchor.
            Run until |offset| < ALIGN_ENTER_PX (10px) -> aligned.
        COARSE phase — box bounding-box centre used when QR not yet visible.
            Brings the robot close enough for QR to appear.
        """
        w = frame.shape[1]

        # Try box QR first — this is the precise FINE anchor
        qr_result = self._box_qr.detect(frame)
        qr_cx = None
        if qr_result.found and qr_result.bbox is not None:
            qx1, qy1, qx2, qy2 = qr_result.bbox
            qr_cx = (qx1 + qx2) // 2

        # Try box detection as COARSE fallback
        box_result = self._box.detect(frame, depth)
        box_cx = box_result.center[0] if box_result.found else None

        # Decide anchor
        if qr_cx is not None:
            anchor_cx = qr_cx
            mode = "FINE (QR)"
        elif box_cx is not None:
            anchor_cx = box_cx
            mode = "COARSE (box)"
        else:
            print("[Stage 3] Nothing detected — holding position")
            return

        correction, offset_px, aligned = self._servo.update(anchor_cx, w)

        if SHOW_WINDOW:
            if qr_cx is not None:
                col = (0, 220, 0) if aligned else (0, 165, 255)
                cv2.rectangle(frame, (qx1, qy1), (qx2, qy2), col, 2)
                cv2.putText(frame, "QR (FINE)", (qx1, qy1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2)
            if box_result.found:
                draw_box_overlay(frame, box_result,
                                 mode="FINE" if qr_cx else "COARSE")
            draw_servo_overlay(frame, anchor_cx, correction, offset_px, aligned)
            cv2.putText(frame, f"Mode: {mode}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 0), 2)

        # Stability gate: robot must hold alignment for ALIGN_STABLE_FRAMES consecutive
        # frames before we trust that it has fully stopped moving.
        _servo_interval = 1.0 / SERVO_SEND_HZ
        _now = time.time()

        if aligned:
            self._align_count += 1
            # Send STOP once when we enter aligned state (not every frame)
            if self._align_count == 1:
                self._teensy.send_servo(0.0)
        else:
            self._align_count = 0
            # Rate-limit servo sends — no need to flood Teensy at camera fps
            if _now - self._last_servo_send >= _servo_interval:
                self._teensy.send_servo(correction)
                self._last_servo_send = _now

        if SHOW_WINDOW:
            # Show stability progress bar in the overlay
            bar_text = f"Stable: {self._align_count}/{ALIGN_STABLE_FRAMES}"
            bar_col  = (0, 220, 0) if aligned else (0, 140, 255)
            cv2.putText(frame, bar_text, (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, bar_col, 2)

        self._mqtt.publish_servo(offset_px, correction, aligned)
        print(f"[Stage 3] {mode}  offset={offset_px:+d}px  "
              f"correction={correction:+.4f}  stable={self._align_count}/{ALIGN_STABLE_FRAMES}")

        if self._align_count >= ALIGN_STABLE_FRAMES and qr_cx is not None:
            print(f"[Stage 3] Stable for {ALIGN_STABLE_FRAMES} frames "
                  f"at offset={offset_px}px -> activating suction cup")
            self._transition(State.GRIPPING)

    def _run_gripping(self, frame):
        """
        Activate suction cup, then track the QR center for GRIP_DELAY_S.
        If the robot drifts during suction, print a warning.
        The suction cup is already active — we can't abort, so we monitor only.
        """
        if self._grip_start is None:
            self._grip_start = time.time()
            self._teensy.send_grip()
            self._teensy.send_servo(0.0)
            self._mqtt.publish_grip()
            print("[Gripping] Suction cup command sent. Tracking center...")

        # Track QR position during grip to detect any robot drift
        w = frame.shape[1]
        qr_result = self._box_qr.detect(frame)
        grip_elapsed = time.time() - self._grip_start

        if qr_result.found and qr_result.bbox is not None:
            qx1, qy1, qx2, qy2 = qr_result.bbox
            qr_cx   = (qx1 + qx2) // 2
            offset  = int(qr_cx - w / 2)

            if abs(offset) > GRIP_DRIFT_WARN_PX:
                print(f"[Gripping] WARNING: drifted {offset:+d}px during grip "
                      f"(t={grip_elapsed:.2f}s)")
                col = (0, 0, 220)   # red = drifted
            else:
                print(f"[Gripping] On-center: offset={offset:+d}px  t={grip_elapsed:.2f}s")
                col = (0, 220, 0)   # green = holding

            if SHOW_WINDOW:
                cv2.rectangle(frame, (qx1, qy1), (qx2, qy2), col, 2)
                cv2.putText(frame, f"Grip offset: {offset:+d}px",
                            (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.65, col, 2)
        else:
            print(f"[Gripping] QR lost during grip — t={grip_elapsed:.2f}s")

        if SHOW_WINDOW:
            pct  = min(grip_elapsed / GRIP_DELAY_S, 1.0)
            bar_w = int(frame.shape[1] * pct)
            cv2.rectangle(frame, (0, frame.shape[0] - 8),
                          (bar_w, frame.shape[0]), (0, 220, 0), -1)
            cv2.putText(frame, "GRIPPING...",
                        (frame.shape[1]//2 - 90, frame.shape[0]//2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 220, 0), 3)

        if grip_elapsed >= GRIP_DELAY_S:
            self._state = State.DONE
            print("[VisionPipeline] Pick complete.")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _transition(self, new_state: State):
        print(f"[VisionPipeline] {self._state.name} -> {new_state.name}")
        self._state       = new_state
        self._stage_start = time.time()
        self._mqtt.publish_stage(new_state.name)

    def _timed_out(self) -> bool:
        if self._no_timeout:
            return False
        limit = STAGE_TIMEOUT.get(self._state.name, None)
        if limit is None:
            return False
        return (time.time() - self._stage_start) > limit

    def _fail(self, reason: str):
        print(f"[VisionPipeline] ERROR — {reason}")
        self._state = State.ERROR
        self._mqtt.publish_error(reason)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AMR Vision Pipeline")
    parser.add_argument("--shelf",   required=True,  help="Expected QR content (shelf ID)")
    parser.add_argument("--sku",     required=True,  help="Expected barcode SKU on box")
    parser.add_argument("--port",    default="COM3", help="Teensy serial port (default COM3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip serial communication (test without robot)")
    parser.add_argument("--no-timeout", action="store_true",
                        help="Disable stage timeouts (useful for manual testing)")
    parser.add_argument("--mqtt-host", default="localhost",
                        help="MQTT broker IP or hostname (default: localhost)")
    args = parser.parse_args()

    if args.no_timeout:
        print("[VisionPipeline] Timeouts DISABLED — take as long as you need per stage")

    pipeline = VisionPipeline(
        shelf_id     = args.shelf,
        expected_sku = args.sku,
        teensy_port  = args.port,
        dry_run      = args.dry_run,
        no_timeout   = args.no_timeout,
        mqtt_host    = args.mqtt_host,
    )

    success = pipeline.run()
    exit(0 if success else 1)
