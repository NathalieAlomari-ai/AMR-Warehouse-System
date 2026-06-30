"""
qr_detector.py
--------------
Stage 1 of the vision pipeline: shelf identity confirmation.

The robot arrives at a target shelf location. This module:
  1. Uses YOLOv8 to find the QR code region in the lower part of the frame.
  2. Crops that region and sends it to pyzbar for decoding.
  3. Compares the decoded content to the expected shelf/order ID.
  4. Requires N consecutive matching frames before confirming (avoids false positives).

Why YOLO first, then pyzbar?
  pyzbar on a full 640x480 frame is slow and unreliable on small/angled QR codes.
  YOLO quickly localises where the QR is, we crop that region, enlarge it,
  enhance contrast with CLAHE, then pass it to pyzbar — much faster and more reliable.

Why the confirm threshold?
  A single frame decode can glitch. Requiring 5 consecutive matching reads
  ensures the robot has a stable, repeatable reading before acting on it.
"""

import cv2
import numpy as np
from ultralytics import YOLO
from pyzbar import pyzbar

# Class ID for QR in our trained model
QR_CLASS_ID = 1

# Minimum detection confidence to attempt decoding
MIN_CONFIDENCE = 0.25   # lowered: catch QR at distance / low contrast

# Expand the YOLO bounding box by this fraction before cropping.
# Larger = more context for pyzbar, better decode at distance.
CROP_PADDING = 0.30

# Minimum side length (pixels) of the crop sent to pyzbar.
# If the YOLO box is small (far away), we upscale to this so pyzbar can read it.
MIN_CROP_PX = 200

# How many consecutive frames must return the same decoded value
# before we consider it confirmed.
CONFIRM_THRESHOLD = 5


def _enhance_for_decode(region: np.ndarray) -> np.ndarray:
    """Grayscale + CLAHE + sharpen — helps in dim/uneven lighting."""
    gray     = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    kernel   = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return cv2.filter2D(enhanced, -1, kernel)


def _try_decode_qr(crop: np.ndarray, full_frame: np.ndarray) -> str:
    """
    Multi-strategy QR decode. Returns the decoded string or '' on failure.

    Tries in order (fastest/most reliable first):
      1. OpenCV QRCodeDetector on crop   — robust for printed QR on paper
      2. pyzbar on raw grayscale crop    — standard, no preprocessing
      3. pyzbar on CLAHE-enhanced crop   — helps with dim/uneven lighting
      4. OpenCV QRCodeDetector on full   — last resort (lets OpenCV find it)
    """
    _cv_qr = cv2.QRCodeDetector()

    # Strategy 1 — OpenCV on crop
    data, _, _ = _cv_qr.detectAndDecode(crop)
    if data:
        return data.strip()

    # Strategy 2 — pyzbar on raw grayscale
    gray    = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    objects = pyzbar.decode(gray)
    if objects:
        return objects[0].data.decode("utf-8").strip()

    # Strategy 3 — pyzbar on CLAHE-enhanced
    enhanced = _enhance_for_decode(crop)
    objects  = pyzbar.decode(enhanced)
    if objects:
        return objects[0].data.decode("utf-8").strip()

    # Strategy 4 — OpenCV on full frame (finds & decodes without our crop)
    data, _, _ = _cv_qr.detectAndDecode(full_frame)
    if data:
        return data.strip()

    return ""


class QRDetector:
    """
    YOLO + pyzbar QR detector with confirmation threshold.

    Usage:
        detector = QRDetector(model, expected_id="SHELF-A3")
        result   = detector.detect(rgb_frame)
        if result.confirmed:
            # shelf identity verified — proceed to raise scissor lift
    """

    def __init__(self, model: YOLO, expected_id: str):
        """
        model:       loaded YOLOv8 YOLO instance (shared with other detectors)
        expected_id: the shelf/order ID string we expect to read from the QR
        """
        self._model       = model
        self._expected_id = expected_id
        self._scan_count  = 0
        self._last_data   = ""
        self.confirmed    = False   # True once threshold is reached

    def reset(self, expected_id: str | None = None):
        """Reset confirmation state. Call between orders."""
        self._scan_count = 0
        self._last_data  = ""
        self.confirmed   = False
        if expected_id is not None:
            self._expected_id = expected_id

    def detect(self, frame: np.ndarray) -> "QRResult":
        """
        Run one frame through YOLO + pyzbar.

        Returns a QRResult with:
            .found      — True if a QR region was detected by YOLO
            .decoded    — decoded string (empty if decode failed)
            .match      — True if decoded string matches expected_id
            .confirmed  — True if match held for CONFIRM_THRESHOLD frames
            .bbox       — (x1,y1,x2,y2) of the YOLO detection, or None
        """
        # Guard: skip bad frames that would crash YOLO
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            return QRResult(found=False)

        try:
            results = self._model(frame, conf=MIN_CONFIDENCE,
                                  classes=[QR_CLASS_ID], verbose=False)
        except Exception as e:
            print(f"[QRDetector] YOLO error (skipping frame): {e}")
            return QRResult(found=False)

        boxes = results[0].boxes

        if len(boxes) == 0:
            # No QR region found — reset streak
            self._scan_count = 0
            return QRResult(found=False)

        # Pick the highest-confidence QR box
        best = max(boxes, key=lambda b: float(b.conf[0]))
        x1, y1, x2, y2 = map(int, best.xyxy[0])
        h, w = frame.shape[:2]

        # Expand bounding box with generous padding so pyzbar has full context
        pad_x = int((x2 - x1) * CROP_PADDING)
        pad_y = int((y2 - y1) * CROP_PADDING)
        x1c   = max(0, x1 - pad_x)
        y1c   = max(0, y1 - pad_y)
        x2c   = min(w, x2 + pad_x)
        y2c   = min(h, y2 + pad_y)

        crop = frame[y1c:y2c, x1c:x2c]

        # Upscale small crops — decoders struggle with QR < 200px per side
        ch, cw = crop.shape[:2]
        if cw < MIN_CROP_PX or ch < MIN_CROP_PX:
            scale = MIN_CROP_PX / min(cw, ch)
            crop  = cv2.resize(crop, (int(cw * scale), int(ch * scale)),
                               interpolation=cv2.INTER_CUBIC)

        # Multi-strategy decode: OpenCV first, pyzbar fallbacks
        decoded_text = _try_decode_qr(crop, frame)

        match = (decoded_text == self._expected_id) if decoded_text else False

        # Update confirmation counter
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

        return QRResult(
            found     = True,
            decoded   = decoded_text,
            match     = match,
            confirmed = self.confirmed,
            bbox      = (x1, y1, x2, y2),
            scan_count = self._scan_count,
        )


class QRResult:
    """Data class holding the output of one QRDetector.detect() call."""
    def __init__(self, found=False, decoded="", match=False,
                 confirmed=False, bbox=None, scan_count=0):
        self.found      = found
        self.decoded    = decoded
        self.match      = match
        self.confirmed  = confirmed
        self.bbox       = bbox
        self.scan_count = scan_count


def draw_qr_overlay(frame: np.ndarray, result: QRResult) -> None:
    """Draw QR detection state on frame (in-place). Used for debugging."""
    if not result.found:
        cv2.putText(frame, "Scanning for QR...",
                    (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2)
        return

    x1, y1, x2, y2 = result.bbox
    if result.confirmed:
        colour = (0, 220, 0)
        status = f"CONFIRMED: {result.decoded}"
    elif result.match:
        colour = (0, 165, 255)
        status = f"Reading ({result.scan_count}/{CONFIRM_THRESHOLD}): {result.decoded}"
    else:
        colour = (0, 0, 220)
        status = f"MISMATCH: got '{result.decoded}'"

    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 50), (30, 30, 30), -1)
    cv2.putText(frame, status, (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, colour, 2)


# ── Standalone test ────────────────────────────────────────────────────────────
# Run:  python amr_vision/qr_detector.py
if __name__ == "__main__":
    from pathlib import Path
    from camera_utils import AstraCamera

    MODEL_PATH  = Path(__file__).parent.parent / "models" / "best.pt"
    EXPECTED_ID = "SHELF-A1"   # change to whatever QR content your test shelf has

    model    = YOLO(str(MODEL_PATH))
    detector = QRDetector(model, expected_id=EXPECTED_ID)

    print(f"QR detector test | looking for: '{EXPECTED_ID}' | Q=quit")
    with AstraCamera() as cam:
        while True:
            ok, rgb, _ = cam.read()
            if not ok:
                break

            result = detector.detect(rgb)
            draw_qr_overlay(rgb, result)

            if result.confirmed:
                print(f"QR CONFIRMED: {result.decoded}")
                detector.reset()  # reset for next read in test mode

            cv2.imshow("QR Detector test (Q=quit)", rgb)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()
