#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_jetson.sh
# AMR Vision Pipeline — Jetson setup script
#
# Run once after cloning the repo on the Jetson:
#   chmod +x setup_jetson.sh
#   ./setup_jetson.sh
#
# Tested on: JetPack 5.x / 6.x (Ubuntu 20.04 / 22.04), aarch64
# ─────────────────────────────────────────────────────────────────────────────

set -e   # stop on first error

echo "========================================"
echo " AMR Vision — Jetson Setup"
echo "========================================"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/6] Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    libzbar0 \
    libzbar-dev \
    libusb-1.0-0-dev \
    v4l-utils \
    git \
    curl \
    build-essential

# Add user to dialout so serial port works without sudo
echo "[1/6] Adding $USER to dialout group (Teensy serial permission)..."
sudo usermod -aG dialout "$USER"
echo "      NOTE: Log out and back in for group change to take effect."

# ── 2. OpenNI2 / Orbbec SDK ───────────────────────────────────────────────────
echo ""
echo "[2/6] OpenNI2 / Orbbec SDK"
echo "      The Orbbec Astra Pro needs the OpenNI2 SDK."
echo "      Download from: https://orbbec3d.com/develop/ → Linux ARM64"
echo "      Then run:  sudo ./install.sh"
echo "      This installs libraries to /usr/lib"
echo "      If installed to a different path, set:"
echo "        export OPENNI2_PATH=/your/path"
echo ""
read -p "      Press ENTER when OpenNI2 is installed, or Ctrl+C to install it first."

# ── 3. Python packages (installed into ROS's system Python, NOT a venv) ───────
# vision_node.py is a single process that imports BOTH rclpy (ROS) and
# ultralytics/opencv/torch (CV/ML). `ros2 run` executes with the system
# Python that has rclpy — an isolated venv would hide rclpy from it and
# raise ModuleNotFoundError on ultralytics if used the other way around.
# So everything goes into the system interpreter. Ubuntu 22.04's pip
# refuses system-wide installs by default (PEP 668) — override it.
echo "[3/6] Upgrading pip (system Python)..."
pip3 install --upgrade pip wheel --break-system-packages

# ── 4. PyTorch for Jetson ─────────────────────────────────────────────────────
echo ""
echo "[4/6] PyTorch for Jetson"
echo "      Standard 'pip install torch' does NOT work on Jetson."
echo "      Install from NVIDIA's Jetson wheels (system Python, --break-system-packages):"
echo ""
echo "      JetPack 5.x (L4T r35):"
echo "        pip3 install torch --break-system-packages --index-url https://developer.download.nvidia.com/compute/redist/jp/v511/"
echo ""
echo "      JetPack 6.x (L4T r36):"
echo "        pip3 install torch --break-system-packages --index-url https://developer.download.nvidia.com/compute/redist/jp/v61/"
echo ""
echo "      Or check: https://forums.developer.nvidia.com/c/agx-autonomous-machines/jetson-embedded-systems/70"
echo ""
read -p "      Press ENTER when PyTorch is installed, or Ctrl+C to install it first."

# Verify torch is installed
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"

# ── 5. Python packages ────────────────────────────────────────────────────────
echo "[5/6] Installing Python packages (system Python)..."
pip3 install -r "$(dirname "$0")/requirements.txt" --break-system-packages

# Remove opencv-python if system opencv is preferred (avoids conflicts)
# pip3 uninstall -y opencv-python
# pip3 install opencv-python-headless --break-system-packages

# ── 6. Verify the camera ──────────────────────────────────────────────────────
echo ""
echo "[6/6] Camera check"
echo "      Plug in the Astra Pro and check it appears:"
echo "        ls /dev/video*"
echo "      Then test the camera:"
echo "        cd ros2_ws/src/amr_vision"
echo "        python3 amr_vision/camera_utils.py"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
echo "========================================"
echo " Setup complete!"
echo ""
echo " All deps are in the system Python (needed since vision_node.py"
echo " imports rclpy AND ultralytics/opencv in the same process)."
echo ""
echo " To run the standalone pipeline (no ROS):"
echo "   cd ros2_ws/src/amr_vision"
echo "   python3 amr_vision/vision_main.py --shelf SHELF-A1 --sku BOX-SKU-001 --dry-run"
echo ""
echo " To run WITH display (if monitor connected):"
echo "   SHOW_WINDOW=1 python3 amr_vision/vision_main.py --shelf SHELF-A1 --sku BOX-SKU-001 --dry-run"
echo ""
echo " To run as a ROS node (after colcon build + source install/setup.bash):"
echo "   ros2 run amr_vision vision_node"
echo ""
echo " To find the Teensy serial port:"
echo "   ls /dev/ttyACM* /dev/ttyUSB*"
echo "   Then: --port /dev/ttyACM0   (or whichever it is)"
echo "========================================"
