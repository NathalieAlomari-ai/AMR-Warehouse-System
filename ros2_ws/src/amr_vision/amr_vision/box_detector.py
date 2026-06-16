"""
box_detector.py
---------------
Detects the cardboard box (class 0) in the camera frame.

Role in the pipeline:
  Stage 3 — COARSE alignment.
  The box bounding box is much larger than the barcode, so it is
  detectable even when the robot is far or misaligned. We use the
  box centre as the servo anchor for coarse correction (offset > 40px).
  Once the box is roughly centred, the barcode becomes reliably visible
  and visual_servo switches to FINE alignment using the barcode centre.

Also used in Stage 2 to confirm a box is visible before attempting
barcode decode (avoids wasting time scanning an empty shelf).

Depth measurement:
  We sample depth over the full inner region of the box bounding box
  (not just the centre pixel) to get a more accurate and stable reading.
  This is better than the barcode-centre depth because the box face
  covers many more valid depth pixels.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from depth_utils import DepthSampler

# Class ID for box in our trained model
BOX_CLASS_ID = 0

# Minimum detection confidence — kept low so box is detected for COARSE servo
# even when the robot is slightly off-angle; QR takes over for FINE alignment.
MIN_CONFIDENCE = 0.25

# Minimum bounding box area (pixels²) to consider a valid box detection.
# Filters out tiny false positives in the background.
MIN_BOX_AREA = 5000

# Coarse alignment threshold: while offset > this, use box centre for servo.
# Below this threshold, switch to barcode centre for fine alignment.
COARSE_THRESHOLD_PX = 40


class BoxDetector:
    """
    Detects the target cardboard box using YOLO class 0.

    Usage:
        detector = BoxDetector(model)
        result   = detector.detect(rgb_frame, depth_frame)
        if result.found:
            # use result.center for coarse servo alignment
            # use result.distance_mm for depth feedback
    """

    def __init__(self, model: YOLO):
        self._model = model
        self._depth = DepthSampler(patch_radius=20)  # larger patch for box face

    def reset(self):
        """Clear depth buffer. Call when box is lost."""
        self._depth.reset()

    def detect(self, frame: np.ndarray,
               depth_frame: np.ndarray) -> "BoxResult":
        """
        Detect the largest box in the frame.

        Returns a BoxResult with:
            .found       — True if a valid box was detected
            .bbox        — (x1, y1, x2, y2)
            .center      — (cx, cy) centre of bounding box
            .distance_mm — stable depth at box centre
            .confidence  — YOLO detection confidence
        """
        results = self._model(frame, conf=MIN_CONFIDENCE,
                              classes=[BOX_CLASS_ID], verbose=False)
        boxes   = results[0].boxes

        if len(boxes) == 0:
            self._depth.reset()
            return BoxResult(found=False)

        # Filter by minimum area, then pick the largest box
        valid = []
        for b in boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            area = (x2 - x1) * (y2 - y1)
            if area >= MIN_BOX_AREA:
                valid.append((area, b))

        if not valid:
            self._depth.reset()
            return BoxResult(found=False)

        _, best    = max(valid, key=lambda t: t[0])
        x1, y1, x2, y2 = map(int, best.xyxy[0])
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        h, w = frame.shape[:2]

        dx          = np.clip(cx, 0, w - 1)
        dy          = np.clip(cy, 0, h - 1)
        distance_mm = self._depth.get(depth_frame, dx, dy)

        return BoxResult(
            found       = True,
            bbox        = (x1, y1, x2, y2),
            center      = (cx, cy),
            distance_mm = distance_mm,
            confidence  = float(best.conf[0]),
        )


class BoxResult:
    """Data class for BoxDetector output."""
    def __init__(self, found=False, bbox=None, center=None,
                 distance_mm=0, confidence=0.0):
        self.found       = found
        self.bbox        = bbox
        self.center      = center
        self.distance_mm = distance_mm
        self.confidence  = confidence


def draw_box_overlay(frame: np.ndarray, result: BoxResult,
                     mode: str = "COARSE") -> None:
    """
    Draw box detection overlay on frame (in-place).
    mode: "COARSE" or "FINE" — shown in the label for clarity.
    """
    if not result.found:
        cv2.putText(frame, "No box detected",
                    (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 200), 2)
        return

    x1, y1, x2, y2 = result.bbox
    cx, cy          = result.center

    colour = (0, 200, 0)   # green for box
    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
    cv2.circle(frame,    (cx, cy), 6, (0, 0, 255), -1)

    label = (f"box {result.confidence:.0%}  "
             f"[{mode}]  "
             f"dist={result.distance_mm}mm" if result.distance_mm > 0
             else f"box {result.confidence:.0%}  [{mode}]  dist=---")
    cv2.putText(frame, label, (x1, y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)


# ── Standalone test ────────────────────────────────────────────────────────────
# Run:  python amr_vision/box_detector.py
if __name__ == "__main__":
    from pathlib import Path
    from camera_utils import AstraCamera

    MODEL_PATH = Path(__file__).parent.parent / "models" / "best.pt"
    model      = YOLO(str(MODEL_PATH))
    detector   = BoxDetector(model)

    print("Box detector test | Q=quit")
    with AstraCamera() as cam:
        while True:
            ok, rgb, depth = cam.read()
            if not ok:
                break

            result = detector.detect(rgb, depth)
            draw_box_overlay(rgb, result)

            if result.found:
                print(f"box  conf={result.confidence:.0%}  "
                      f"cx={result.center[0]}  dist={result.distance_mm}mm")

            cv2.imshow("Box Detector test (Q=quit)", rgb)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()
