"""
test_model.py
-------------
Quick sanity check: load best.pt and run it on the Astra Pro RGB stream.
Run this BEFORE building the full pipeline to confirm the model works on your laptop.

Usage:
    python scripts/test_model.py

Controls:
    Q  — quit
    S  — save current frame as screenshot
"""

import cv2
import sys
from pathlib import Path
from ultralytics import YOLO

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_PATH   = Path(__file__).parent.parent / "models" / "best.pt"
CONFIDENCE   = 0.35     # only show detections above this confidence
CAMERA_INDEX = 0        # try 0 first, change to 1 if wrong camera opens

# Class colours: box=green, qr=blue, barcode=orange
CLASS_COLOURS = {
    0: (0, 200, 0),     # box     — green
    1: (255, 100, 0),   # qr      — blue
    2: (0, 140, 255),   # barcode — orange
}
CLASS_NAMES = {0: "box", 1: "qr", 2: "barcode"}
# ─────────────────────────────────────────────────────────────────────────────


def main():
    if not MODEL_PATH.exists():
        print(f"[ERROR] Model not found: {MODEL_PATH}")
        print("        Copy best.pt into ros2_ws/src/amr_vision/models/")
        sys.exit(1)

    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(str(MODEL_PATH))
    print("Model loaded. Classes:", model.names)

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"Camera index {CAMERA_INDEX} failed, trying index 1 ...")
        cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("[ERROR] Cannot open camera. Check USB connection.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Camera open. Press Q to quit, S to save screenshot.")
    screenshot_n = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Failed to read frame.")
            break

        # Run inference
        results = model(frame, conf=CONFIDENCE, verbose=False)

        # Draw each detection manually so we can colour by class
        for box in results[0].boxes:
            cls_id = int(box.cls[0])
            conf   = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            colour = CLASS_COLOURS.get(cls_id, (200, 200, 200))
            label  = f"{CLASS_NAMES.get(cls_id, str(cls_id))} {conf:.0%}"

            cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
            # Label background
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), colour, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # Detection count overlay
        n = len(results[0].boxes)
        cv2.putText(frame, f"Detections: {n}  |  conf>={CONFIDENCE}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 220, 220), 2)

        cv2.imshow("AMR Vision — Model Test (Q=quit  S=screenshot)", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('s'):
            fname = f"screenshot_{screenshot_n:03d}.jpg"
            cv2.imwrite(fname, frame)
            print(f"Saved: {fname}")
            screenshot_n += 1

    cap.release()
    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()
