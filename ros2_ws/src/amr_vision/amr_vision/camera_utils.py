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

# Path to the OpenNI2 redistributable binaries
# Windows: installed by the Astra SDK installer
# Jetson/Linux: change to "/usr/lib"
OPENNI2_PATH = r"C:\OpenNI2\Bin"

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

    def __init__(self, rgb_index: int = 0):
        """
        rgb_index: OpenCV camera index for the RGB stream.
                   Usually 0 or 1 depending on other connected cameras.
                   If the wrong camera opens, change this to 1.
        """
        # Initialise OpenNI2 for the depth stream
        openni2.initialize(OPENNI2_PATH)
        self._device       = openni2.Device.open_any()
        self._depth_stream = self._device.create_depth_stream()
        self._depth_stream.start()

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

        # Read depth from OpenNI2
        raw        = self._depth_stream.read_frame()
        buf        = raw.get_buffer_as_uint16()
        depth      = np.frombuffer(buf, dtype=np.uint16).copy()
        depth      = depth.reshape((FRAME_H, FRAME_W))

        return True, rgb, depth

    def close(self):
        """Release all camera resources. Always call this on shutdown."""
        self._cap.release()
        self._depth_stream.stop()
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
