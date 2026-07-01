# Waypoint Navigation Guide — AMR Warehouse Robot

This guide covers how to save shelf/location waypoints and send the robot to them autonomously.  
You need **two machines running at the same time**: the robot (amrobot-desktop) and the laptop (nathalie-Latitude-E6430).

---

## Prerequisites (One-Time Setup)

### On the Laptop — add domain ID permanently
```bash
echo "export ROS_DOMAIN_ID=30" >> ~/.bashrc
source ~/.bashrc
```

### On the Laptop — install keyboard teleoperation (once)
```bash
sudo apt install ros-humble-teleop-twist-keyboard
```

---

## Every Session — Full Startup Sequence

Follow this order every time you want to use the robot.

---

### TERMINAL 1 — Robot: Start Navigation Stack

SSH into the robot or open a terminal on it, then run:

```bash
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 launch amr_bringup robot_navigation.launch.py
```

**What to expect:**
- All Nav2 nodes start (map_server, amcl, controller_server, bt_navigator, etc.)
- LiDAR starts spinning
- Teensy serial bridge connects
- Message: `AMCL cannot publish a pose — Please set the initial pose...` → this is NORMAL, it waits for you to set the pose in RViz

**Leave this terminal running the whole session. Never close it.**

---

### TERMINAL 2 — Laptop: Open RViz

```bash
export ROS_DOMAIN_ID=30
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
rviz2 -d ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/rviz/navigation.rviz
```

**What to do in RViz:**
1. Wait for the map (white/gray warehouse layout) to appear
2. Click **"2D Pose Estimate"** in the top toolbar (arrow icon)
3. Click on the map **where the robot is physically located** in the room
4. Hold the mouse and **drag in the direction the robot is facing**, then release
5. A green cloud of arrows (AMCL particles) will appear around the robot
6. The robot model (white box) will snap to your chosen position

**Important:** The robot will not navigate until this step is done.

---

### TERMINAL 3 — Laptop: Keyboard Teleoperation (to drive to waypoints)

```bash
export ROS_DOMAIN_ID=30
source /opt/ros/humble/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args --remap cmd_vel:=cmd_vel_joy
```

**Keys:**
| Key | Action |
|-----|--------|
| `i` | Forward |
| `,` | Backward |
| `j` | Rotate left |
| `l` | Rotate right |
| `k` | **Stop** |
| `u` | Forward + left |
| `o` | Forward + right |
| `q` / `z` | Increase / decrease speed |

**Note:** This terminal must stay focused (clicked) for keyboard input to work.

---

### TERMINAL 4 — Laptop: Waypoint Commands (save + navigate)

This terminal is used for all waypoint operations.

#### Setup (run once per session):
```bash
export ROS_DOMAIN_ID=30
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash

# If action server is not found, restart the ROS2 daemon first:
ros2 daemon stop
ros2 daemon start
```

---

## Saving Waypoints

### How to save a waypoint

1. **Drive** the robot to the shelf/location using keyboard (Terminal 3)
2. **Run** in Terminal 4:

```bash
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_saver.py <name>
```

Replace `<name>` with any label you want. Examples:

```bash
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_saver.py shelf_A
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_saver.py shelf_B
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_saver.py home
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_saver.py dropoff
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_saver.py pickup_station
```

**What to expect:**
```
[INFO] Waiting for AMCL pose to save as "shelf_A"...
[INFO] Saved "shelf_A": x=-5.755  y=-2.752  yaw=0.009
[INFO] File: .../config/waypoints.yaml
```

The waypoint is saved automatically to:
```
ros2_ws/src/amr_navigation/config/waypoints.yaml
```

### View all saved waypoints

```bash
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_navigator.py --list
```

Output example:
```
Saved waypoints:
  dropoff              x= -2.100  y= 0.500  yaw= 3.141
  home                 x=  0.000  y= 0.000  yaw= 0.000
  shelf_A              x= -5.755  y=-2.752  yaw= 0.009
  shelf_B              x=  1.200  y= 3.100  yaw= 1.571
```

---

## Sending the Robot to a Waypoint

```bash
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_navigator.py <name>
```

Examples:
```bash
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_navigator.py shelf_A
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_navigator.py home
python3 ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/scripts/waypoint_navigator.py dropoff
```

**What to expect:**
```
[INFO] Sending robot to "shelf_A" (x=-5.755, y=-2.752, yaw=0.009)
[INFO] Waiting for navigate_to_pose action server...
[INFO] Goal accepted — robot is on its way...
[INFO] Arrived at "shelf_A"!
```

The robot will:
1. Plan a path from its current position to the waypoint
2. Drive along the path (avoiding obstacles)
3. Stop when it reaches the goal
4. Print "Arrived!" when done

**Note:** You can override the robot at any time by pressing keys in the keyboard teleop terminal (joystick has priority 100 vs navigation priority 10 in twist_mux).

---

## Saving Waypoints to Git (Make Them Permanent)

After saving new waypoints, commit them so they are not lost:

```bash
cd ~/AMR-Warehouse-System
git add ros2_ws/src/amr_navigation/config/waypoints.yaml
git commit -m "waypoints: add shelf_A, shelf_B, home, dropoff locations"
git push origin feature/slam-setup
```

---

## Troubleshooting

### "Waiting for AMCL pose..." — script hangs and never saves
- You have not set the **2D Pose Estimate** in RViz yet
- Go to RViz → click "2D Pose Estimate" → click on map where robot is

### "navigate_to_pose action server not available"
- Restart the ROS2 daemon on the laptop:
```bash
ros2 daemon stop
ros2 daemon start
```
- Then retry the waypoint_navigator command

### Robot drifts off course / gets lost
- Use "2D Pose Estimate" in RViz to reset its position on the map
- Drive it back to a known location with keyboard first, then relocalize

### Topics not visible on laptop (`ros2 topic list` only shows 2 topics)
- Domain ID mismatch — make sure `ROS_DOMAIN_ID=30` is exported
- Restart daemon:
```bash
ros2 daemon stop
export ROS_DOMAIN_ID=30
ros2 daemon start
ros2 topic list
```

### Duplicate nodes warning (`robot_state_publisher x2`)
- The robot launch was started twice — Ctrl+C on robot and relaunch once cleanly

---

## Speed Settings

Current speed: **0.15 m/s** (set in `nav2_params.yaml`).  
To change it, edit these three values in:
```
ros2_ws/src/amr_navigation/config/nav2_params.yaml
```

| Parameter | Location | Current Value |
|-----------|----------|---------------|
| `max_vel_x` | controller_server → FollowPath | `0.15` |
| `max_speed_xy` | controller_server → FollowPath | `0.15` |
| `max_velocity[0]` | velocity_smoother | `0.15` |

After editing, rebuild on the robot:
```bash
cd ~/AMR-Warehouse-System/ros2_ws
colcon build --packages-select amr_navigation
source install/setup.bash
```

---

## File Locations

| File | Purpose |
|------|---------|
| `ros2_ws/src/amr_navigation/config/waypoints.yaml` | Saved waypoint coordinates |
| `ros2_ws/src/amr_navigation/scripts/waypoint_saver.py` | Script to save current pose as waypoint |
| `ros2_ws/src/amr_navigation/scripts/waypoint_navigator.py` | Script to navigate to a waypoint |
| `ros2_ws/src/amr_navigation/config/nav2_params.yaml` | All Nav2 tuning parameters |
| `ros2_ws/src/amr_bringup/launch/robot_navigation.launch.py` | Main robot launch file |
| `ros2_ws/src/amr_navigation/rviz/navigation.rviz` | RViz layout for navigation |
