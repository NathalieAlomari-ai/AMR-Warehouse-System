"""
config.py
---------
Platform-aware configuration for the AMR vision pipeline.

Automatically detects whether it is running on:
  - Windows (development / testing on laptop)
  - Jetson (deployment on robot)

Override any value via environment variable before running:
    OPENNI2_PATH=/my/path TEENSY_PORT=/dev/ttyUSB0 python vision_main.py ...
"""

import os
import platform

# ── Platform detection ────────────────────────────────────────────────────────
IS_JETSON  = platform.system() == "Linux" and "aarch64" in platform.machine()
IS_WINDOWS = platform.system() == "Windows"

# ── Camera ────────────────────────────────────────────────────────────────────
# Path to the OpenNI2 shared library directory.
# Windows: installed by the Astra Pro SDK at C:\OpenNI2\Bin
# Jetson:  installed via apt or the Orbbec SDK — usually /usr/lib
_default_openni2 = "/usr/lib/aarch64-linux-gnu" if IS_JETSON else r"C:\OpenNI2\Bin"
OPENNI2_PATH = os.getenv("OPENNI2_PATH", _default_openni2)

# OpenCV camera index for the Astra Pro RGB stream.
# If the wrong camera opens, set RGB_CAM_INDEX=1 in your environment.
RGB_CAM_INDEX = int(os.getenv("RGB_CAM_INDEX", "0"))

# Depth on/off. Set DEPTH_ENABLED=0 to skip OpenNI2 entirely and run RGB-only.
# Use this on a Jetson where the depth sensor isn't powered yet: a FAILED
# OpenNI2 device-open leaves a dangling USB thread that segfaults the process,
# so when depth can't work it is safer never to touch OpenNI2 at all. QR
# reading and cup-centering only need RGB. Set back to 1 once the depth sensor
# opens cleanly (e.g. on a powered USB hub).
DEPTH_ENABLED = bool(int(os.getenv("DEPTH_ENABLED", "1")))

# ── Serial port ───────────────────────────────────────────────────────────────
# Teensy 4.1 serial port name.
# Windows: "COM3", "COM4" … check Device Manager
# Jetson:  "/dev/ttyACM0" or "/dev/ttyUSB0" — check with: ls /dev/tty*
#          Give your user permission once: sudo usermod -aG dialout $USER
_default_port = "/dev/ttyACM0" if IS_JETSON else "COM3"
TEENSY_PORT = os.getenv("TEENSY_PORT", _default_port)

# ── Display ───────────────────────────────────────────────────────────────────
# Show the OpenCV debug window.
# On headless Jetson (no monitor): set SHOW_WINDOW=1 only if you have a display.
# On Windows: always show.
_default_show = "0" if IS_JETSON else "1"
SHOW_WINDOW = bool(int(os.getenv("SHOW_WINDOW", _default_show)))

# ── Servo rate limit ─────────────────────────────────────────────────────────
# Maximum rate (Hz) at which SERVO commands are sent to Teensy.
# Camera runs at ~20-30 fps — we do NOT need to send a correction every frame.
# 10 Hz gives the robot time to respond before the next correction arrives.
SERVO_SEND_HZ = 10   # commands per second
