"""
vision_main.py
--------------
The main vision pipeline state machine.

This file is the ONLY file your robot's main process should import and run.
It coordinates all 3 stages in order:

  STAGE_1: QR confirmation
    Camera detects QR on the lower part of the shelf.
    Decoded content is compared to the expected shelf ID.
    On confirmation → signal navigation to raise scissor lift.

  STAGE_2: Barcode confirmation + depth measurement
    Scissor lift has reached target height.
    Camera detects barcode on the box and confirms the SKU.
    Depth is measured to determine how far the robot must approach.
    On confirmation → send approach distance to Teensy.

  STAGE_3: Visual servo alignment (two-phase)
    Robot drives forward to approach distance (Teensy handles that).
    COARSE phase: box centre used for servo — box is large, always visible.
    FINE phase:   barcode centre used once offset < 40px — more precise.
    When barcode offset < 10px → send suction cup activation command.

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
from enum import Enum, auto
from pathlib import Path
from ultralytics import YOLO

from camera_utils     import AstraCamera
from qr_detector      import QRDetector, draw_qr_overlay
from barcode_detector import BarcodeDetector, draw_barcode_overlay
from box_detector     import BoxDetector, draw_box_overlay, COARSE_THRESHOLD_PX
from visual_servo     import VisualServo, draw_servo_overlay
from teensy_comm      import TeensyComm

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

# Whether to show the live camera window (set False for headless Jetson deployment)
SHOW_WINDOW = True
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
                 teensy_port: str = "COM3", dry_run: bool = False):
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

        self._qr      = QRDetector(self._model, expected_id=shelf_id)
        self._barcode = BarcodeDetector(self._model, expected_sku=expected_sku)
        self._box     = BoxDetector(self._model)
        self._servo   = VisualServo()
        self._teensy  = TeensyComm(port=teensy_port, dry_run=dry_run)

        self._state      = State.STAGE_1
        self._stage_start = time.time()
        self._grip_start  = None

    def run(self):
        """
        Main loop. Opens camera, processes frames, transitions states.
        Blocks until the pick is complete (DONE) or fails (ERROR).
        """
        with AstraCamera() as cam:
            print(f"[VisionPipeline] Camera open. Starting in state: {self._state.name}")

            while self._state not in (State.DONE, State.ERROR):
                ok, rgb, depth = cam.read()
                if not ok:
                    self._fail("Camera read failed")
                    break

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

        print(f"[VisionPipeline] Final state: {self._state.name}")
        return self._state == State.DONE

    # ── Stage handlers ─────────────────────────────────────────────────────────

    def _run_stage1(self, frame):
        """Stage 1: find and confirm QR code on shelf."""
        result = self._qr.detect(frame)
        if SHOW_WINDOW:
            draw_qr_overlay(frame, result)

        if result.confirmed:
            print(f"[Stage 1] QR confirmed: '{result.decoded}' — signalling lift UP")
            self._teensy.send_lift_up()   # navigation team raises scissor lift
            self._transition(State.STAGE_2)

    def _run_stage2(self, frame, depth):
        """Stage 2: confirm barcode SKU and measure approach distance."""
        result = self._barcode.detect(frame, depth)
        if SHOW_WINDOW:
            draw_barcode_overlay(frame, result)

        if result.confirmed:
            if result.distance_mm > 0:
                print(f"[Stage 2] SKU confirmed: '{result.decoded}'  "
                      f"distance: {result.distance_mm} mm")
                self._teensy.send_approach(result.distance_mm)
                self._transition(State.STAGE_3)
            else:
                # SKU confirmed but depth is not valid yet — keep waiting
                print("[Stage 2] SKU confirmed, waiting for valid depth...")

    def _run_stage3(self, frame, depth):
        """
        Stage 3: two-phase visual servo alignment.

        COARSE phase — use BOX centre (large, always visible even when misaligned).
            Run until |offset| < COARSE_THRESHOLD_PX.
        FINE phase   — use BARCODE centre (precise, small target).
            Run until |offset| < ALIGN_ENTER_PX (10px) → aligned.
        """
        w = frame.shape[1]

        # Always try barcode first (it is the ground truth anchor)
        bc_results = self._model(frame, conf=0.30, classes=[2], verbose=False)
        bc_boxes   = bc_results[0].boxes
        barcode_cx = None
        if bc_boxes:
            best       = max(bc_boxes, key=lambda b: float(b.conf[0]))
            bx1, by1, bx2, by2 = map(int, best.xyxy[0])
            barcode_cx = (bx1 + bx2) // 2

        # Try box detection as coarse fallback
        box_result = self._box.detect(frame, depth)
        box_cx     = box_result.center[0] if box_result.found else None

        # Decide which anchor to use
        if barcode_cx is not None:
            # Barcode visible → use it regardless of phase
            anchor_cx = barcode_cx
            mode      = "FINE (barcode)"
        elif box_cx is not None:
            # Only box visible → coarse alignment
            anchor_cx = box_cx
            mode      = "COARSE (box)"
        else:
            # Nothing detected — hold position
            print("[Stage 3] Nothing detected — holding position")
            return

        correction, offset_px, aligned = self._servo.update(anchor_cx, w)

        if SHOW_WINDOW:
            if barcode_cx is not None:
                col = (0, 220, 0) if aligned else (0, 140, 255)
                cv2.rectangle(frame, (bx1, by1), (bx2, by2), col, 2)
            if box_result.found:
                draw_box_overlay(frame, box_result,
                                 mode="FINE" if barcode_cx else "COARSE")
            draw_servo_overlay(frame, anchor_cx, correction, offset_px, aligned)
            cv2.putText(frame, f"Mode: {mode}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 0), 2)

        print(f"[Stage 3] {mode}  offset={offset_px:+d}px  "
              f"correction={correction:+.4f}  aligned={aligned}")

        if aligned and barcode_cx is not None:
            # Only declare aligned when we have the precise barcode anchor
            print(f"[Stage 3] FINE aligned at offset={offset_px}px — activating suction cup")
            self._transition(State.GRIPPING)
        elif not aligned:
            self._teensy.send_servo(correction)

    def _run_gripping(self, frame):
        """Activate suction cup, wait for GRIP_DELAY_S, then declare DONE."""
        if self._grip_start is None:
            self._grip_start = time.time()
            self._teensy.send_grip()
            print("[Gripping] Suction cup command sent.")

        cv2.putText(frame, "GRIPPING...", (frame.shape[1]//2 - 80, frame.shape[0]//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 220, 0), 3)

        if time.time() - self._grip_start >= GRIP_DELAY_S:
            self._state = State.DONE
            print("[VisionPipeline] Pick complete.")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _transition(self, new_state: State):
        print(f"[VisionPipeline] {self._state.name} → {new_state.name}")
        self._state       = new_state
        self._stage_start = time.time()

    def _timed_out(self) -> bool:
        limit = STAGE_TIMEOUT.get(self._state.name, None)
        if limit is None:
            return False
        return (time.time() - self._stage_start) > limit

    def _fail(self, reason: str):
        print(f"[VisionPipeline] ERROR — {reason}")
        self._state = State.ERROR


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AMR Vision Pipeline")
    parser.add_argument("--shelf",   required=True,  help="Expected QR content (shelf ID)")
    parser.add_argument("--sku",     required=True,  help="Expected barcode SKU on box")
    parser.add_argument("--port",    default="COM3", help="Teensy serial port (default COM3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip serial communication (test without robot)")
    args = parser.parse_args()

    pipeline = VisionPipeline(
        shelf_id     = args.shelf,
        expected_sku = args.sku,
        teensy_port  = args.port,
        dry_run      = args.dry_run,
    )

    success = pipeline.run()
    exit(0 if success else 1)
