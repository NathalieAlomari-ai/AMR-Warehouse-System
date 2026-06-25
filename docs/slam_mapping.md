# SLAM Mapping Guide

## One-Time Setup (do this once on the robot machine)

Add to `~/.bashrc` on **amrobot-desktop** so every terminal gets the right domain:
```bash
echo 'export ROS_DOMAIN_ID=30' >> ~/.bashrc
echo 'export ROS_LOCALHOST_ONLY=0' >> ~/.bashrc
source ~/.bashrc
```

Your PC (nathalie-Latitude-E6430) already has `ROS_DOMAIN_ID=30` set.

Both machines must be on the **same WiFi network**.

---

## Every Time You Map

### Step 1 — Robot Terminal 1: Launch everything
```bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 launch amr_bringup robot_slam.launch.py
```
Wait until you see: `Registering sensor: [Custom Described Lidar]`

**Leave this terminal open the whole time. Never close it while mapping.**

### Step 2 — Robot Terminal 2: Teleop
```bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args --remap cmd_vel:=/cmd_vel
```

**Click on this terminal window to give it keyboard focus before pressing keys.**

| Key | Action |
|-----|--------|
| `i` | Forward |
| `,` | Backward |
| `j` | Rotate left |
| `l` | Rotate right |
| `k` | Stop |

### Step 3 — PC: Open RViz
```bash
source /opt/ros/humble/setup.bash
rviz2
```

In RViz:
1. **Global Options → Fixed Frame** → type `map`
2. **Add → By topic → /map → Map**
3. **Add → By topic → /scan → LaserScan**
4. **File → Save Config As** → save as `~/slam.rviz` so you don't need to redo this

Drive the robot at least 10–20 cm. The map appears within 5 seconds of movement.

---

## Save the Map (when done mapping)

Run on the robot while the launch is still running:
```bash
mkdir -p ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/maps
ros2 run nav2_map_server map_saver_cli -f ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/maps/warehouse_map --ros-args -p save_map_timeout:=10.0
```

You will see: `Map saved successfully`

Then commit to git:
```bash
cd ~/AMR-Warehouse-System
git add ros2_ws/src/amr_navigation/maps/
git commit -m "feat: update warehouse map"
git push
```

---

## Leaving the Lab

1. **Save the map** (steps above) and push to git
2. Press `k` in teleop to stop the robot
3. Press `Ctrl+C` in Terminal 1 to stop the launch
4. Close RViz on your PC
5. Power off the robot safely

---

## Troubleshooting

**Robot not moving when pressing `i`**
- Click on the teleop terminal window — it needs keyboard focus
- Check all terminals on amrobot-desktop have `ROS_DOMAIN_ID=30`

**Map not showing in RViz / "fixed frame no data"**
- Drive the robot 20 cm first — map only appears after movement
- Make sure Fixed Frame is exactly `map` (lowercase)
- Run `ros2 topic list | grep map` on the PC — if `/map` shows, drive more

**"queue is full" warnings in the launch terminal**
- This is normal at startup for 1–2 seconds, then it clears automatically

**Two bringup launches running at the same time (serial port error)**
- Kill everything first: `pkill -f robot_slam; pkill -f slam_toolbox; pkill -f serial_bridge; pkill -f sllidar; pkill -f ekf_node`
- Wait 3 seconds, then relaunch once

**map_saver fails**
- Use `--ros-args -p save_map_timeout:=10.0` (adds 10s wait window)
