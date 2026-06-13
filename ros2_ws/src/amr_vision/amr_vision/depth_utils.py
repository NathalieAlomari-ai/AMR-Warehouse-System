"""
depth_utils.py
--------------
All depth measurement logic in one place.

The Astra Pro depth sensor is noisy. A single pixel reading fluctuates
by +-50mm even for a still object. We use two techniques to stabilise it:

  1. SPATIAL averaging:  sample a 10x10 patch around the target pixel,
                         filter out invalid readings (0 = no return,
                         <600mm = too close, >8000mm = out of range),
                         then average what's left.

  2. TEMPORAL smoothing: keep a rolling buffer of the last N valid readings,
                         return the MEDIAN (not mean) because median rejects
                         spike outliers — e.g. a single bad frame of 0mm
                         does not pull the average down.

Usage:
    from depth_utils import DepthSampler

    sampler = DepthSampler()
    distance_mm = sampler.get(depth_frame, cx, cy)
    # distance_mm is 0 if no valid reading is available yet
"""

import numpy as np
from collections import deque
from camera_utils import DEPTH_MIN_MM, DEPTH_MAX_MM

# How many pixels on each side of the centre to include in the patch.
# A value of 10 means a 21x21 pixel window (conservative — avoids edge bleed).
PATCH_RADIUS = 10

# Number of frames to keep in the rolling buffer.
# Higher = smoother but slower to react to real distance changes.
BUFFER_SIZE = 10


class DepthSampler:
    """
    Stateful depth sampler with spatial averaging and temporal median filter.

    One instance per tracked object.
    Call reset() when you lose tracking (object not detected).
    """

    def __init__(self, patch_radius: int = PATCH_RADIUS, buffer_size: int = BUFFER_SIZE):
        self._patch_radius = patch_radius
        self._buffer       = deque(maxlen=buffer_size)

    def reset(self):
        """Clear the rolling buffer. Call when detection is lost."""
        self._buffer.clear()

    def get(self, depth_frame: np.ndarray, cx: int, cy: int) -> int:
        """
        Get a stable depth reading at pixel (cx, cy).

        Args:
            depth_frame: uint16 array from AstraCamera.read(), values in mm
            cx, cy:      pixel coordinate of the target centre

        Returns:
            Stable distance in mm, or 0 if not enough valid data yet.
        """
        raw = self._sample_patch(depth_frame, cx, cy)

        # Only add to buffer if the raw reading is valid
        if raw > 0:
            self._buffer.append(raw)

        if len(self._buffer) == 0:
            return 0

        # Median across the buffer — rejects spike outliers
        return int(np.median(self._buffer))

    def _sample_patch(self, depth_frame: np.ndarray, cx: int, cy: int) -> int:
        """
        Average depth over a patch centred on (cx, cy).
        Filters out pixels that are zero, below minimum, or above maximum range.
        Returns 0 if fewer than 3 valid pixels are found (not enough data).
        """
        h, w = depth_frame.shape
        r    = self._patch_radius

        # Clamp patch to frame boundaries
        x1 = max(0, cx - r)
        x2 = min(w, cx + r + 1)
        y1 = max(0, cy - r)
        y2 = min(h, cy + r + 1)

        patch = depth_frame[y1:y2, x1:x2].astype(np.float32)

        # Keep only valid readings
        valid = patch[(patch >= DEPTH_MIN_MM) & (patch <= DEPTH_MAX_MM)]

        if len(valid) < 3:
            return 0

        return int(np.mean(valid))

    @property
    def confidence(self) -> float:
        """How full the buffer is, as a fraction 0.0–1.0. < 0.5 means unstable."""
        return len(self._buffer) / self._buffer.maxlen


# ── Standalone test ────────────────────────────────────────────────────────────
# Run:  python amr_vision/depth_utils.py
if __name__ == "__main__":
    import cv2
    from camera_utils import AstraCamera

    print("Testing DepthSampler ... press Q to quit")
    sampler = DepthSampler()

    with AstraCamera() as cam:
        while True:
            ok, rgb, depth = cam.read()
            if not ok:
                break

            h, w  = rgb.shape[:2]
            cx, cy = w // 2, h // 2

            dist_mm = sampler.get(depth, cx, cy)

            # Visualise
            cv2.drawMarker(rgb, (cx, cy), (0, 255, 255),
                           cv2.MARKER_CROSS, 30, 2)

            if dist_mm > 0:
                label = f"{dist_mm} mm  ({dist_mm/10:.1f} cm)  conf={sampler.confidence:.0%}"
                color = (0, 255, 0)
            else:
                label = "OUT OF RANGE"
                color = (0, 0, 255)

            cv2.putText(rgb, label, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            cv2.imshow("DepthSampler test (Q=quit)", rgb)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()
