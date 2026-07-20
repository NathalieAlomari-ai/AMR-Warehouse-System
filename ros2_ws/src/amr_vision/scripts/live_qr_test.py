#!/usr/bin/env python3
"""
live_qr_test.py
---------------
Headless live QR test for the Jetson — prints what the Astra RGB camera decodes,
frame by frame. No display window needed (works over SSH).

Run:
    export DEPTH_ENABLED=0
    cd ~/AMR-Warehouse-System/ros2_ws/src/amr_vision
    python3 scripts/live_qr_test.py

Ctrl+C to stop.

Reads:
    "QR bbox ... decoded: 'SHELF-A1'"  -> camera + YOLO + QR decode all working
    "QR bbox ... decoded: ''"          -> YOLO sees the QR but can't decode it
                                          (move closer / better light / hold flat)
    "scanning... (no QR in view)"      -> YOLO isn't finding a QR at all
    "frame read failed"                -> camera read problem
"""

import os
import sys
from pathlib import Path

# Make the flat amr_vision modules (camera_utils, qr_detector, config) importable.
ROOT = Path(__file__).resolve().parent.parent          # .../src/amr_vision
sys.path.insert(0, str(ROOT / "amr_vision"))

from ultralytics import YOLO
from camera_utils import AstraCamera
from qr_detector import QRDetector

MODEL_PATH = ROOT / "models" / "best.pt"


def main() -> None:
    print(f"[live_qr_test] model         : {MODEL_PATH}")
    print(f"[live_qr_test] DEPTH_ENABLED : {os.getenv('DEPTH_ENABLED', '1')}")
    print("[live_qr_test] loading YOLO model ...")
    model = YOLO(str(MODEL_PATH))
    qr = QRDetector(model, expected_id="")   # expected_id unused: we just report

    print("--- hold a QR / shelf label to the camera (Ctrl+C to stop) ---")
    found = 0
    with AstraCamera() as cam:
        i = 0
        while True:
            i += 1
            ok, rgb, _ = cam.read()
            if not ok:
                print(i, "frame read failed")
                continue
            r = qr.detect(rgb)
            if r.found:
                found += 1
                print(i, "QR bbox", r.bbox, "| decoded:", repr(r.decoded))
            elif i % 20 == 0:
                print(i, "scanning... (no QR in view)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[live_qr_test] stopped.")
