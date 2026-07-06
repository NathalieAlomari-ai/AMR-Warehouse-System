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
    python3-venv \
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

# ── 3. Python virtual environment ─────────────────────────────────────────────
echo "[3/6] Creating Python virtual environment..."
VENV_DIR="$(dirname "$0")/.venv_jetson"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip wheel

# ── 4. PyTorch for Jetson ─────────────────────────────────────────────────────
echo ""
echo "[4/6] PyTorch for Jetson"
echo "      Standard 'pip install torch' does NOT work on Jetson."
echo "      Install from NVIDIA's Jetson wheels:"
echo ""
echo "      JetPack 5.x (L4T r35):"
echo "        pip install torch --index-url https://developer.download.nvidia.com/compute/redist/jp/v511/"
echo ""
echo "      JetPack 6.x (L4T r36):"
echo "        pip install torch --index-url https://developer.download.nvidia.com/compute/redist/jp/v61/"
echo ""
echo "      Or check: https://forums.developer.nvidia.com/c/agx-autonomous-machines/jetson-embedded-systems/70"
echo ""
read -p "      Press ENTER when PyTorch is installed, or Ctrl+C to install it first."

# Verify torch is installed
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"

# ── 5. Python packages ────────────────────────────────────────────────────────
echo "[5/6] Installing Python packages..."
pip install -r "$(dirname "$0")/requirements.txt"

# Remove opencv-python if system opencv is preferred (avoids conflicts)
# pip uninstall -y opencv-python
# pip install opencv-python-headless

# ── 6. Verify the camera ──────────────────────────────────────────────────────
echo ""
echo "[6/6] Camera check"
echo "      Plug in the Astra Pro and check it appears:"
echo "        ls /dev/video*"
echo "      Then test the camera:"
echo "        source $VENV_DIR/bin/activate"
echo "        cd ros2_ws/src/amr_vision"
echo "        python amr_vision/camera_utils.py"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
echo "========================================"
echo " Setup complete!"
echo ""
echo " To activate the environment:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo " To run the vision pipeline:"
echo "   cd ros2_ws/src/amr_vision"
echo "   python amr_vision/vision_main.py --shelf SHELF-A1 --sku BOX-SKU-001 --dry-run"
echo ""
echo " To run WITH display (if monitor connected):"
echo "   SHOW_WINDOW=1 python amr_vision/vision_main.py --shelf SHELF-A1 --sku BOX-SKU-001 --dry-run"
echo ""
echo " To find the Teensy serial port:"
echo "   ls /dev/ttyACM* /dev/ttyUSB*"
echo "   Then: --port /dev/ttyACM0   (or whichever it is)"
echo "========================================"
