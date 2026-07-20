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
echo "[1/7] Installing system packages..."
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
echo "[1/7] Adding $USER to dialout group (Teensy serial permission)..."
sudo usermod -aG dialout "$USER"
echo "      NOTE: Log out and back in for group change to take effect."

# ── 2. OpenNI2 / Orbbec SDK ───────────────────────────────────────────────────
echo ""
echo "[2/7] OpenNI2 / Orbbec SDK"
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
# So everything goes into the system interpreter. pip >=23.0.1 refuses
# system-wide installs by default (PEP 668) and needs --break-system-packages;
# older pip (e.g. 22.0.2 on stock Ubuntu 22.04) doesn't understand that flag
# at all and errors out if you pass it. Detect support instead of assuming it.
PIP_FLAGS=""
if pip3 install --help 2>/dev/null | grep -q -- --break-system-packages; then
    PIP_FLAGS="--break-system-packages"
fi

echo "[3/7] Upgrading pip (system Python)..."
pip3 install --upgrade pip wheel $PIP_FLAGS

# ── 4. PyTorch for Jetson ─────────────────────────────────────────────────────
# NVIDIA's Jetson torch wheels are compiled against NumPy's 1.x ABI, so numpy
# must be pinned <2 BEFORE torch is installed, or torch crashes on import.
echo ""
echo "[4/7] PyTorch for Jetson"
echo "      Standard 'pip install torch' does NOT work on Jetson — it pulls a"
echo "      generic (non-Jetson) build with no GPU support. Find your exact"
echo "      wheel filename in NVIDIA's directory listing first:"
echo "        https://developer.download.nvidia.com/compute/redist/jp/"
echo "      (open your JetPack's v## folder -> pytorch/ -> pick a cp310 .whl"
echo "       matching your L4T revision, e.g. v61 = JetPack 6.x)"
echo ""
echo "      Then, with system Python:"
echo "        pip3 install $PIP_FLAGS 'numpy==1.26.1'"
echo "        pip3 install --no-cache $PIP_FLAGS <full .whl URL you found>"
echo ""
echo "      Or check: https://forums.developer.nvidia.com/c/agx-autonomous-machines/jetson-embedded-systems/70"
echo ""
read -p "      Press ENTER when PyTorch is installed, or Ctrl+C to install it first."

# Verify torch is installed
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"

# ── 5. torchvision, built from source ─────────────────────────────────────────
# NVIDIA does not publish prebuilt Jetson torchvision wheels. It must be
# compiled from source against the exact torch build installed above.
# Check https://github.com/pytorch/vision#installation for the torchvision
# tag matching your torch version (e.g. torch 2.5.x -> torchvision v0.20.0).
echo ""
echo "[5/7] torchvision (built from source — NVIDIA does not ship a wheel for this)"
echo "      This takes 30-60+ minutes on an Orin Nano. Example for torch 2.5.x:"
echo ""
echo "        sudo apt-get install -y libjpeg-dev zlib1g-dev libpython3-dev \\"
echo "            libavcodec-dev libavformat-dev libswscale-dev"
echo "        cd ~ && git clone --branch v0.20.0 https://github.com/pytorch/vision torchvision"
echo "        cd torchvision && export BUILD_VERSION=0.20.0"
echo "        python3 setup.py install --user"
echo ""
echo "      IMPORTANT: verify from a DIFFERENT directory afterward (e.g. cd ~),"
echo "      never from inside ~/torchvision — Python will import the raw source"
echo "      checkout there instead of the installed, compiled package."
echo ""
read -p "      Press ENTER when torchvision is built and installed, or Ctrl+C to do it first."

# Verify torchvision's C extension actually loads (run from $HOME, not the
# torchvision source checkout, to avoid shadowing the installed package)
( cd "$HOME" && python3 -c "import torchvision; from torchvision.ops import nms; print(f'torchvision {torchvision.__version__} C extension ok')" )

# ── 6. Remaining Python packages, WITHOUT letting pip touch torch/torchvision ─
# ultralytics declares an unpinned 'torch>=1.8.0' dependency. A plain
# `pip install -r requirements.txt` lets pip "resolve" that by silently
# uninstalling the correct Jetson torch/torchvision above and replacing them
# with generic PyPI builds that have no Jetson GPU support. --no-deps stops
# pip from touching anything's dependencies — install exactly what's named
# and nothing else.
echo "[6/7] Installing remaining Python packages (system Python, --no-deps)..."
pip3 install ultralytics --no-deps $PIP_FLAGS
pip3 install -r "$(dirname "$0")/requirements.txt" --no-deps $PIP_FLAGS

# Remove opencv-python if system opencv is preferred (avoids conflicts)
# pip3 uninstall -y opencv-python
# pip3 install opencv-python-headless --no-deps $PIP_FLAGS

# Re-verify torch/torchvision weren't silently swapped by the step above
( cd "$HOME" && python3 -c "import torch, torchvision; print(f'torch {torch.__version__} CUDA:{torch.cuda.is_available()} | torchvision {torchvision.__version__}')" )

# ── 7. Verify the camera ──────────────────────────────────────────────────────
echo ""
echo "[7/7] Camera check"
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
