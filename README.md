# AMR Warehouse System

An Autonomous Mobile Robot (AMR) for pharmaceutical warehouse picking, built on ROS2 Humble running on a Jetson Orin Nano. The robot autonomously navigates to shelf locations, verifies QR codes, and retrieves medicine boxes using a scissor-lift and vacuum gripper.

---

## Team

| Name | Role |
|---|---|
| **Nathalie** | Team Lead · Autonomy · ROS2 Navigation (Nav2 / SLAM) |
| **Abdalla** | Vision (Camera / QR Detection) · Web GUI & MQTT Bridge |
| **Zahra** | Motion Control (Teensy firmware) · Project Reports |
| **Mahanna** | Payload (Scissor Lift / Gripper) · CAD Design · Fabrication |

---

## Repository Structure

```
AMR-Warehouse-System/
│
├── ros2_ws/                    # ROS2 Humble workspace (Jetson Orin Nano)
│   └── src/
│       ├── amr_description/    # URDF/Xacro robot model, Gazebo, RViz2 configs
│       ├── amr_navigation/     # Nav2 params, SLAM Toolbox config, nav launch files
│       ├── amr_bringup/        # Top-level launch files — single entry point to start the robot
│       └── amr_vision/         # QR detection & camera processing nodes (Python)
│
├── firmware/                   # PlatformIO project for Teensy 4.1
│                               # micro-ROS over USB · motor PWM · encoder odometry · IMU
│
├── web_app/                    # Flask dashboard + MQTT broker bridge
│                               # Sends mission orders → ROS2 via /cmd_vel and custom topics
│
└── docs/
    ├── reports/                # Project reports and documentation (Zahra)
    └── cad_and_fab/            # CAD files, BOM, fabrication drawings (Mahanna)
```

---

## Hardware

| Component | Details |
|---|---|| Compute | Jetson Orin Nano 8 GB · Ubuntu 22.04 · ROS2 Humble |
| MCU | Teensy 4.1 · PlatformIO · micro-ROS over USB serial |
| Motors | AMX 775 planetary DC · 24 V · 120 RPM · 1:51 gear ratio |
| Motor Driver | BTS7960 H-bridge (one per motor) |
| LiDAR | Slamtec RPLIDAR C1 → `/scan` |
| Depth Camera | Orbbec Astra Pro · 0.6–8 m range → `/camera/depth/points` |
| IMU | BNO055 on Teensy Wire1 → `/imu/data` |
| Chassis | 600 × 500 × 300 mm · wheel track 550 mm · wheel radius 65 mm |

---

## Getting Started

### Prerequisites

```bash
# ROS2 Humble + Gazebo Classic
sudo apt install ros-humble-desktop ros-humble-gazebo-ros-pkgs \
     ros-humble-nav2-bringup ros-humble-slam-toolbox \
     ros-humble-robot-localization ros-humble-xacro \
     ros-humble-joint-state-publisher-gui
```

### Clone

```bash
git clone https://github.com/AMR-Warehouse-Team/AMR-Warehouse-System.git
cd AMR-Warehouse-System
```

### Build the ROS2 workspace

```bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
```

### View robot model in RViz2

```bash
ros2 launch amr_description display.launch.py
```

### Run headless Gazebo simulation

```bash
ros2 launch amr_description launch_sim.launch.py
```

---

## Key ROS2 Topics

| Topic | Direction | Type |
|---|---|---|
| `/cmd_vel` | Jetson → Teensy | `geometry_msgs/Twist` |
| `/odom` | Teensy → Jetson | `nav_msgs/Odometry` |
| `/imu/data` | Teensy → Jetson | `sensor_msgs/Imu` |
| `/scan` | LiDAR | `sensor_msgs/LaserScan` |
| `/camera/depth/points` | Orbbec Astra | `sensor_msgs/PointCloud2` |
| `/qr_detection` | Vision node | custom |
| `/lift_command` | Payload node | custom |

---

## Testing & Documentation

**Start here on test day:** [`docs/TESTING_COMMANDS.md`](docs/TESTING_COMMANDS.md) — a full
per-subsystem command reference for testing each part of the stack individually and then
end-to-end (vision, aux hardware, drive/odometry/IMU, LiDAR, Nav2 + RViz, SLAM, MQTT, and
the coordinator mission).

> Every ROS 2 terminal must source the workspace and set a **matching** `ROS_DOMAIN_ID` on
> the Jetson and the laptop (we use `export ROS_DOMAIN_ID=30`).

| Doc | What it covers |
|---|---|
| [`docs/TESTING_COMMANDS.md`](docs/TESTING_COMMANDS.md) | Full per-subsystem + full-stack testing commands |
| [`docs/RUN_full_scenario.md`](docs/RUN_full_scenario.md) | Test-day run narrative and startup order |
| [`docs/TEST_RUNBOOK_vision.md`](docs/TEST_RUNBOOK_vision.md) | Vision node deep-dive and troubleshooting |
| [`docs/MQTT_GUIDE.md`](docs/MQTT_GUIDE.md) | MQTT + dashboard from scratch |
| [`docs/waypoint_navigation_guide.md`](docs/waypoint_navigation_guide.md) | Saving and navigating named waypoints |
| [`docs/slam_mapping.md`](docs/slam_mapping.md) | Building a map with SLAM |
