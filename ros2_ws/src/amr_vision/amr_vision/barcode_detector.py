"""
barcode_detector.py
-------------------
Stage 2 of the vision pipeline: item identity confirmation + depth measurement.

After the scissor lift rises to the pre-known shelf height, the camera
now faces the box. This module:

  1. Uses YOLOv8 to locate the barcode on the box face.
  2. Crops the barcode region and decodes it with pyzbar.
  3. Compares the decoded SKU to the expected order SKU.
  4. Uses the barcode bounding box centre as the anchor point for:
       - Depth measurement (how far is the box from the robot?)
       - Visual servo alignment (is the box centred in the frame?)

Why use the barcode centre for depth/alignment (not the full box)?
  The barcode is a small, specific region on the box face. Its centre
  gives us a more precise anchor than the full box outline, which may
  extend beyond the visible area.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from pyzbar import pyzbar
from depth_utils import DepthSampler

# Class ID for barcode in our trained model
BARCODE_CLASS_ID = 2

# Minimum detection confidence
MIN_CONFIDENCE = 0.30

# Padding around the YOLO crop before passing to pyzbar
CROP_PADDING = 0.20

# Consecutive matching frames required before confirming SKU
CONFIRM_THRESHOLD = 5


def _enhance_for_decode(region: np.ndarray) -> np.ndarray:
    """Greyscale + CLAHE + sharpen — same as qr_detector."""
    gray     = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    kernel   = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return cv2.filter2D(enhanced, -1, kernel)


class BarcodeDetector:
    """
    YOLO + pyzbar barcode detector with SKU confirmation and depth measurement.

    Usage:
        detector = BarcodeDetector(model, expected_sku="SKU-7821")
        result   = detector.detect(rgb_frame, depth_frame)
        if result.confirmed:
            send_to_teensy(result.distance_mm)  # approach command
    """

    def __init__(self, model: YOLO, expected_sku: str):
        """
        model:        loaded YOLOv8 YOLO instance (shared with other detectors)
        expected_sku: the SKU / barcode value we expect on the target box
        """
        self._model        = model
        self._expected_sku = expected_sku
        self._scan_count   = 0
        self._last_data    = ""
        self._depth        = DepthSampler()
        self.confirmed     = False

    def reset(self, expected_sku: str | None = None):
        """Reset state. Call between picks or on detection loss."""
        self._scan_count = 0
        self._last_data  = ""
        self.confirmed   = False
        self._depth.reset()
        if expected_sku is not None:
            self._expected_sku = expected_sku

    def detect(self, frame: np.ndarray,
               depth_frame: np.ndarray) -> "BarcodeResult":
        """
        Run one frame.

        Returns a BarcodeResult with:
            .found       — True if barcode region detected by YOLO
            .decoded     — decoded SKU string (empty if decode failed)
            .match       — True if decoded SKU matches expected_sku
            .confirmed   — True if match held for CONFIRM_THRESHOLD frames
            .bbox        — (x1,y1,x2,y2) of the YOLO box, or None
            .center      — (cx, cy) pixel centre of the barcode
            .distance_mm — stable depth reading at the barcode centre (mm)
        """
        results = self._model(frame, conf=MIN_CONFIDENCE,
                              classes=[BARCODE_CLASS_ID], verbose=False)
        boxes   = results[0].boxes

        if len(boxes) == 0:
            self._scan_count = 0
            self._depth.reset()
            return BarcodeResult(found=False)

        # Pick highest-confidence detection
        best       = max(boxes, key=lambda b: float(b.conf[0]))
        x1, y1, x2, y2 = map(int, best.xyxy[0])
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        h, w = frame.shape[:2]

        # Measure depth at barcode centre
        dx          = np.clip(cx, 0, w - 1)
        dy          = np.clip(cy, 0, h - 1)
        distance_mm = self._depth.get(depth_frame, dx, dy)

        # Crop + enhance for decode
        pad_x = int((x2 - x1) * CROP_PADDING)
        pad_y = int((y2 - y1) * CROP_PADDING)
        x1c   = max(0, x1 - pad_x)
        y1c   = max(0, y1 - pad_y)
        x2c   = min(w, x2 + pad_x)
        y2c   = min(h, y2 + pad_y)
        crop  = frame[y1c:y2c, x1c:x2c]

        enhanced     = _enhance_for_decode(crop)
        decoded_text = ""
        objects      = pyzbar.decode(enhanced)
        if objects:
            decoded_text = objects[0].data.decode("utf-8").strip()

        match = (decoded_text == self._expected_sku) if decoded_text else False

        if match:
            if decoded_text == self._last_data:
                self._scan_count += 1
            else:
                self._scan_count = 1
                self._last_data  = decoded_text
            if self._scan_count >= CONFIRM_THRESHOLD:
                self.confirmed = True
        else:
            self._scan_count = 0

        return BarcodeResult(
            found       = True,
            decoded     = decoded_text,
            match       = match,
            confirmed   = self.confirmed,
            bbox        = (x1, y1, x2, y2),
            center      = (cx, cy),
            distance_mm = distance_mm,
            scan_count  = self._scan_count,
        )


class BarcodeResult:
    """Data class holding the output of one BarcodeDetector.detect() call."""
    def __init__(self, found=False, decoded="", match=False,
                 confirmed=False, bbox=None, center=None,
                 distance_mm=0, scan_count=0):
        self.found       = found
        self.decoded     = decoded
        self.match       = match
        self.confirmed   = confirmed
        self.bbox        = bbox
        self.center      = center      # (cx, cy) — used by visual_servo
        self.distance_mm = distance_mm # used by teensy_comm for approach
        self.scan_count  = scan_count


def draw_barcode_overlay(frame: np.ndarray, result: BarcodeResult) -> None:
    """Draw barcode detection state on frame (in-place). Used for debugging."""
    if not result.found:
        cv2.putText(frame, "Scanning for barcode...",
                    (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2)
        return

    x1, y1, x2, y2 = result.bbox
    cx, cy          = result.center

    if result.confirmed:
        colour = (0, 220, 0)
        sku_label = f"SKU OK: {result.decoded}"
    elif result.match:
        colour = (0, 165, 255)
        sku_label = f"Reading ({result.scan_count}/{CONFIRM_THRESHOLD}): {result.decoded}"
    else:
        colour = (0, 0, 220)
        sku_label = f"MISMATCH: '{result.decoded}'"

    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
    cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)

    # Info panel
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 55), (30, 30, 30), -1)
    cv2.putText(frame, sku_label, (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)

    dist_label = (f"Distance: {result.distance_mm} mm  ({result.distance_mm/10:.1f} cm)"
                  if result.distance_mm > 0 else "Distance: OUT OF RANGE")
    cv2.putText(frame, dist_label, (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)


# ── Standalone test ────────────────────────────────────────────────────────────
# Run:  python amr_vision/barcode_detector.py
if __name__ == "__main__":
    from pathlib import Path
    from camera_utils import AstraCamera

    MODEL_PATH   = Path(__file__).parent.parent / "models" / "best.pt"
    EXPECTED_SKU = "123456789"   # change to the barcode on your test box

    model    = YOLO(str(MODEL_PATH))
    detector = BarcodeDetector(model, expected_sku=EXPECTED_SKU)

    print(f"Barcode detector test | looking for SKU: '{EXPECTED_SKU}' | Q=quit")
    with AstraCamera() as cam:
        while True:
            ok, rgb, depth = cam.read()
            if not ok:
                break

            result = detector.detect(rgb, depth)
            draw_barcode_overlay(rgb, result)

            if result.confirmed:
                print(f"BARCODE CONFIRMED: {result.decoded}  dist={result.distance_mm}mm")

            cv2.imshow("Barcode Detector test (Q=quit)", rgb)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()
