"""
camera_utils.py
---------------
Wrapper around the Orbbec Astra Pro camera.
Provides one object (AstraCamera) that gives you:
    - RGB frame  (640x480 BGR, same format as OpenCV)
    - Depth frame (640x480 uint16, values in millimetres)

Why a wrapper?
  Every other module just calls camera.read() and gets both frames.
  All OpenNI2 initialisation, error handling, and resource cleanup
  is in one place — not scattered across every file.

Windows note:
  OpenNI2 must be installed at C:\OpenNI2\
  The Astra Pro appears as two USB devices:
    - RGB  → standard UVC webcam  (cv2.VideoCapture)
    - Depth → OpenNI2 stream       (openni2)
  They are NOT synchronised at the hardware level; we read them
  as close together as possible in software.

Jetson note (when porting):
  Change OPENNI2_PATH to "/usr/lib" (installed via apt on Ubuntu/Jetson).
  RGB camera index may differ — check with `ls /dev/video*`.
"""

import cv2
import numpy as np
from openni import openni2
from config import OPENNI2_PATH, RGB_CAM_INDEX, DEPTH_ENABLED

# Astra Pro valid depth range (hardware limitation)
DEPTH_MIN_MM = 600    # 60 cm — closer than this returns 0
DEPTH_MAX_MM = 8000   # 8 m   — further than this returns 0

# Resolution — Astra Pro native RGB and depth resolution
FRAME_W = 640
FRAME_H = 480


class AstraCamera:
    """
    Opens the Astra Pro RGB and depth streams.
    Call read() in your main loop to get both frames simultaneously.
    Call close() when done (or use as a context manager: with AstraCamera() as cam).
    """

    def __init__(self, rgb_index: int = RGB_CAM_INDEX):
        """
        rgb_index: OpenCV camera index for the RGB stream.
                   Usually 0 or 1 depending on other connected cameras.
                   If the wrong camera opens, change this to 1.
        """
        # ── Depth via OpenNI2 (OPTIONAL) ─────────────────────────────────────
        # The depth sensor (IR projector) is power-hungry and may fail to open
        # on an under-powered / hub-chained USB port ("USB transfer timeout").
        # That must NOT take down vision: QR reading and cup-centering run on
        # RGB alone. So if depth can't open we log it and degrade to RGB-only;
        # read() then returns a zeroed depth frame and the pipeline keeps going.
        # Depth lights up automatically once the sensor is on a good port /
        # powered hub — no code change needed.
        self._depth_stream       = None
        self._openni_initialized = False
        self.depth_available     = False
        if not DEPTH_ENABLED:
            # Depth explicitly disabled (DEPTH_ENABLED=0). Do NOT touch OpenNI2 at
            # all — a failed device-open can leave a USB thread that segfaults the
            # whole process. Pure RGB via OpenCV below.
            print("[AstraCamera] DEPTH_ENABLED=0 — skipping OpenNI2, RGB-only mode.")
        else:
            try:
                openni2.initialize(OPENNI2_PATH)
                self._openni_initialized = True
                self._device       = openni2.Device.open_any()
                self._depth_stream = self._device.create_depth_stream()
                self._depth_stream.start()
                self.depth_available = True
                print(f"[AstraCamera] Depth stream open (OpenNI2 @ {OPENNI2_PATH})")
            except Exception as e:
                print(f"[AstraCamera] WARNING: depth unavailable — {e}")
                print("[AstraCamera] Running RGB-ONLY: QR + centering work; "
                      "approach-distance is disabled until the depth sensor connects.")
                # Best-effort teardown so OpenNI2's USB thread doesn't linger and
                # segfault. If depth keeps failing, run with DEPTH_ENABLED=0.
                try:
                    if self._openni_initialized:
                        openni2.unload()
                except Exception:
                    pass
                self._openni_initialized = False
                self._depth_stream       = None

        # Initialise OpenCV for the RGB stream
        self._cap = cv2.VideoCapture(rgb_index)
        if not self._cap.isOpened():
            # Try the other index as a fallback
            fallback = 1 if rgb_index == 0 else 0
            self._cap = cv2.VideoCapture(fallback)

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

        if not self._cap.isOpened():
            raise RuntimeError("Cannot open Astra Pro RGB camera. Check USB connection.")

    def read(self) -> tuple[bool, np.ndarray | None, np.ndarray | None]:
        """
        Read one RGB and one depth frame.

        Returns:
            ok          — False if either stream failed
            rgb_frame   — BGR image, shape (480, 640, 3), dtype uint8
            depth_frame — depth image, shape (480, 640), dtype uint16, values in mm
        """
        ret, rgb = self._cap.read()
        if not ret:
            return False, None, None

        # Read depth from OpenNI2 — or a zeroed frame in RGB-only mode.
        if self._depth_stream is not None:
            raw   = self._depth_stream.read_frame()
            buf   = raw.get_buffer_as_uint16()
            depth = np.frombuffer(buf, dtype=np.uint16).copy().reshape((FRAME_H, FRAME_W))
        else:
            depth = np.zeros((FRAME_H, FRAME_W), dtype=np.uint16)  # RGB-only fallback

        return True, rgb, depth

    def close(self):
        """Release all camera resources. Always call this on shutdown."""
        if getattr(self, "_cap", None) is not None:
            self._cap.release()
        if self._depth_stream is not None:
            self._depth_stream.stop()
        if self._openni_initialized:
            openni2.unload()

    # Context manager support — lets you write: with AstraCamera() as cam:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── Standalone test ────────────────────────────────────────────────────────────
# Run this file directly to verify the camera opens correctly:
#   python amr_vision/camera_utils.py
if __name__ == "__main__":
    print("Testing AstraCamera ... press Q to quit")
    with AstraCamera() as cam:
        while True:
            ok, rgb, depth = cam.read()
            if not ok:
                print("Frame read failed")
                break

            # Visualise depth as a colour map
            clipped   = np.clip(depth.astype(np.float32), DEPTH_MIN_MM, DEPTH_MAX_MM)
            norm      = cv2.normalize(clipped, None, 0, 255, cv2.NORM_MINMAX)
            colourmap = cv2.applyColorMap(norm.astype(np.uint8), cv2.COLORMAP_JET)

            combined = np.hstack([rgb, colourmap])
            cv2.imshow("AstraCamera test — RGB | Depth (Q=quit)", combined)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()
    print("Camera closed cleanly.")
