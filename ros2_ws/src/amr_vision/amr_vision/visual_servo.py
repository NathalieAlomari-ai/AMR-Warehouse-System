"""
visual_servo.py
---------------
Stage 3 of the vision pipeline: centre the box in the camera frame.

After the barcode is confirmed and the robot has approached to the right
distance, we need to align the robot laterally so the suction cup is
directly in front of the box centre.

How it works:
  - Calculate the horizontal pixel offset: box_cx - frame_centre_x
  - Multiply by a proportional gain Kp to get a correction value
  - Send the correction to Teensy (Teensy moves the whole robot left/right)
  - Repeat until the offset is within the dead-zone (+-10 pixels)

Hysteresis:
  We use TWO thresholds instead of one:
    ALIGN_ENTER = 10 px  — only enter "aligned" state when offset < 10
    ALIGN_EXIT  = 25 px  — only leave "aligned" state when offset > 25
  This prevents the robot from oscillating in and out of aligned state
  near the boundary, which would cause jerky movement.

Correction value:
  The correction is a signed float (positive = move right, negative = move left).
  The MAGNITUDE is proportional to the pixel error.
  Teensy interprets this as a velocity or step command — see teensy_comm.py.
"""

# Proportional gain: pixels of error → correction magnitude
# Tuned from visualservoing.py test: 0.008 gave good response without oscillation
Kp = 0.008

# Hysteresis thresholds (pixels)
ALIGN_ENTER_PX = 10   # enter aligned state when |offset| < this
ALIGN_EXIT_PX  = 25   # leave aligned state when |offset| > this


class VisualServo:
    """
    Stateful proportional controller for lateral robot alignment.

    Usage:
        servo = VisualServo()
        correction, offset_px, aligned = servo.update(box_cx, frame_width)
        if aligned:
            # send suction cup activation
        else:
            teensy.send_servo(correction)
    """

    def __init__(self, kp: float = Kp,
                 align_enter: int = ALIGN_ENTER_PX,
                 align_exit:  int = ALIGN_EXIT_PX):
        self._kp          = kp
        self._align_enter = align_enter
        self._align_exit  = align_exit
        self.aligned      = False

    def reset(self):
        """Reset alignment state. Call when barcode is lost."""
        self.aligned = False

    def update(self, box_cx: int, frame_width: int) -> tuple[float, int, bool]:
        """
        Compute one servo correction step.

        Args:
            box_cx:       horizontal pixel position of the barcode/box centre
            frame_width:  width of the camera frame in pixels (usually 640)

        Returns:
            correction — float, positive=right, negative=left, 0.0 if aligned
            offset_px  — signed pixel distance from frame centre (diagnostic)
            aligned    — True if robot is within the dead-zone
        """
        frame_cx   = frame_width / 2.0
        offset     = box_cx - frame_cx          # positive = box is right of centre
        correction = float(offset) * self._kp  # proportional correction

        # Hysteresis state machine
        if self.aligned:
            # Already aligned — only leave if error grows large enough
            if abs(offset) > self._align_exit:
                self.aligned = False
        else:
            # Not aligned — enter only when error is small enough
            if abs(offset) < self._align_enter:
                self.aligned = True

        # When aligned, send zero correction — robot holds position
        if self.aligned:
            correction = 0.0

        return correction, int(offset), self.aligned

    @property
    def direction(self) -> str:
        """Human-readable direction string for the last update. For display only."""
        return "ALIGNED"  # caller should check the return value of update()


def draw_servo_overlay(frame, box_cx: int, correction: float,
                       offset_px: int, aligned: bool) -> None:
    """
    Draw servo alignment visualisation on frame (in-place).
    Shows: frame centre line, offset line, status panel.
    """
    import cv2
    h, w = frame.shape[:2]

    # Vertical centre line
    cv2.line(frame, (w // 2, 0), (w // 2, h), (180, 180, 180), 1)

    # Horizontal line from box centre to frame centre
    if box_cx is not None:
        cy = h // 2
        cv2.line(frame, (box_cx, cy), (w // 2, cy), (255, 0, 255), 2)
        cv2.circle(frame, (box_cx, cy), 6, (0, 0, 255), -1)

    # Status panel
    if aligned:
        status = "ALIGNED"
        colour = (0, 220, 0)
    elif correction > 0:
        status = "MOVE RIGHT"
        colour = (0, 140, 255)
    else:
        status = "MOVE LEFT"
        colour = (0, 140, 255)

    cv2.rectangle(frame, (0, h - 70), (360, h), (30, 30, 30), -1)
    cv2.putText(frame, status,
                (10, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2)
    cv2.putText(frame, f"Offset: {offset_px:+d}px   Correction: {correction:+.4f}",
                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)


# ── Standalone test ────────────────────────────────────────────────────────────
# Run:  python amr_vision/visual_servo.py
# Uses the trained model to detect barcodes and runs the servo loop.
if __name__ == "__main__":
    import cv2
    from pathlib import Path
    from ultralytics import YOLO
    from camera_utils import AstraCamera
    from depth_utils import DepthSampler
    import numpy as np

    MODEL_PATH = Path(__file__).parent.parent / "models" / "best.pt"
    BARCODE_CLASS_ID = 2
    model  = YOLO(str(MODEL_PATH))
    servo  = VisualServo()
    depth  = DepthSampler()

    print("Visual servo test | Q=quit")
    with AstraCamera() as cam:
        while True:
            ok, rgb, depth_frame = cam.read()
            if not ok:
                break

            h, w = rgb.shape[:2]
            results = model(rgb, conf=0.30, classes=[BARCODE_CLASS_ID], verbose=False)
            boxes   = results[0].boxes

            if boxes:
                best     = max(boxes, key=lambda b: float(b.conf[0]))
                x1, y1, x2, y2 = map(int, best.xyxy[0])
                cx       = (x1 + x2) // 2
                cy       = (y1 + y2) // 2
                dist_mm  = depth.get(depth_frame, cx, cy)

                correction, offset_px, aligned = servo.update(cx, w)

                col = (0, 220, 0) if aligned else (0, 140, 255)
                cv2.rectangle(rgb, (x1, y1), (x2, y2), col, 2)
                draw_servo_overlay(rgb, cx, correction, offset_px, aligned)

                dist_text = f"Dist: {dist_mm}mm" if dist_mm > 0 else "Dist: OUT OF RANGE"
                cv2.putText(rgb, dist_text, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                print(f"offset={offset_px:+4d}px  correction={correction:+.4f}  "
                      f"aligned={aligned}  dist={dist_mm}mm")
            else:
                servo.reset()
                depth.reset()
                cv2.putText(rgb, "No barcode detected",
                            (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 200), 2)

            cv2.imshow("Visual Servo test (Q=quit)", rgb)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()
