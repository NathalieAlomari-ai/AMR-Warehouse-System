# AMR Warehouse — Full Testing Command Reference

One place for **every command you need to test each subsystem individually**, then the
whole stack together. Pulled from the real node interfaces on
`feature/system-integration` (topics, message types, params, and firmware command
vocabulary are all verified against the source, not guessed).

Test **bottom-up**: prove each box works on its own before wiring the next one on top.
Stop at the first failure — a broken layer makes everything above it lie.

---

## 0. Golden rules (read once)

- **Every terminal** that runs a ROS 2 command needs the environment sourced first:
  ```bash
  source /opt/ros/humble/setup.bash
  source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
  export ROS_DOMAIN_ID=30      # pick ONE number; it MUST match on every machine
  ```
  Different `ROS_DOMAIN_ID` (or different Wi-Fi) = nodes silently can't see each other.
- Build after pulling code: `cd ~/AMR-Warehouse-System/ros2_ws && colcon build --symlink-install && source install/setup.bash`.
  `--symlink-install` means Python edits take effect on node **restart** (no rebuild).
- The **Jetson** holds the robot, LiDAR, camera and Teensy. The **laptop** runs RViz and
  the dashboard. Commands are labelled **[Jetson]** / **[Laptop]** / **[Either]**.
- If a pasted command picks up stray `~` characters, run once: `bind 'set enable-bracketed-paste off'`.

Quick health checks that work anywhere:
```bash
ros2 node list           # who's alive
ros2 topic list          # what topics exist
ros2 topic hz <topic>    # is it actually publishing, and how fast
ros2 topic echo <topic>  # see the messages
```

---

## 1. Vision — camera + QR  [Jetson]

**Contract:** coordinator asks on `/vision/request` (`std_msgs/String`: `SHELF_QR` | `BOX_QR`),
vision answers on `/vision/result` (`std_msgs/String`: `OK <sku>` | `FAIL`).
On `BOX_QR` it also centres the cup by rotating the robot via its `cmd_vel_topic`
(default `/cmd_vel_vision`).

### 1a. Camera-only sanity check (no ROS)
```bash
cd ~/AMR-Warehouse-System/ros2_ws/src/amr_vision
export DEPTH_ENABLED=0
python3 scripts/live_qr_test.py
```
Proves the camera opens and QR decoding works before any ROS is involved.

### 1b. Start the vision node
```bash
cd ~/AMR-Warehouse-System/ros2_ws && source install/setup.bash
export DEPTH_ENABLED=0                                   # RGB-only; mission never uses depth
# export AMR_MODEL_PATH=~/AMR-Warehouse-System/ros2_ws/src/amr_vision/models/best.pt   # if best.pt not auto-found
ros2 run amr_vision vision_node
```
Healthy: `Ready — waiting on /vision/request (SHELF_QR | BOX_QR)`.

### 1c. Test SHELF_QR (second terminal, Jetson)
```bash
ros2 topic echo /vision/result &                                  # watch replies
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'SHELF_QR'}"
```
Hold the shelf QR to the camera. **Pass:** `data: "OK <shelf text>"`.

### 1d. Test BOX_QR + centring (robot must be free to rotate!)
```bash
ros2 topic echo /cmd_vel_vision &                                 # watch the centring rotation
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
```
**Pass:** `angular.z` values stream out, then `data: "OK <sku>"`.

> Testing vision **standalone** without twist_mux running? Point it straight at `/cmd_vel`:
> ```bash
> ros2 run amr_vision vision_node --ros-args -p cmd_vel_topic:=/cmd_vel
> ```
> (Then echo `/cmd_vel` instead of `/cmd_vel_vision`.)

### Vision troubleshooting
| Symptom | Fix (edit `amr_vision/vision_node.py`, then **restart node** — no rebuild) |
|---|---|
| Rotates the **wrong way** on BOX_QR | `INVERT_TURN = True` |
| Too fast / jerky | `MAX_TURN_RATE = 0.3`, `ANCHOR_SMOOTHING = 0.3` |
| Stalls short of centre | `MIN_TURN_RATE = 0.05` |
| `FAIL` (can't read code) | Bigger/flatter/better-lit QR; raise `SHELF_QR_TIMEOUT`/`BOX_QR_TIMEOUT` but keep `BOX_QR_TIMEOUT + CENTER_TIMEOUT < 30 s` |
| `FileNotFoundError: best.pt` | `export AMR_MODEL_PATH=...` (best.pt is gitignored — must already be on the Jetson) |
| Camera segfault / `USB transfer timeout` | `export DEPTH_ENABLED=0` in that terminal |

---

## 2. Aux hardware — lift / stepper / pump  [Jetson]

**`serial_bridge_node` is the ONLY process allowed to open `/dev/ttyACM0`.** All aux
hardware is driven by publishing plain strings to `/aux/command`; the firmware replies
with `EVT …` lines that appear on `/aux/status`.

### 2a. Pre-flight
```bash
ls /dev/ttyACM*          # Teensy present? (usually /dev/ttyACM0)
groups | grep dialout    # your user must be in the dialout group
```

### 2b. Start the bridge
```bash
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=30
ros2 run amr_hardware serial_bridge_node
```

### 2c. Watch firmware events (second terminal) — keep this open
```bash
ros2 topic echo /aux/status      # every "EVT ..." line the Teensy emits
```

### 2d. Exercise each actuator (third terminal)
```bash
ros2 topic pub --once /aux/command std_msgs/msg/String "{data: 'STEP EXT'}"   # → EVT STEP DONE
ros2 topic pub --once /aux/command std_msgs/msg/String "{data: 'STEP RET'}"   # → EVT STEP DONE
ros2 topic pub --once /aux/command std_msgs/msg/String "{data: 'LIFT 200'}"   # → EVT LIFT DONE
ros2 topic pub --once /aux/command std_msgs/msg/String "{data: 'LIFT 0'}"     # → EVT LIFT DONE
ros2 topic pub --once /aux/command std_msgs/msg/String "{data: 'PUMP ON'}"    # → EVT PUMP ON
ros2 topic pub --once /aux/command std_msgs/msg/String "{data: 'PUMP OFF'}"   # → EVT PUMP OFF
```

**Full firmware command vocabulary** (`firmware/integration/src/main.cpp`):

| Command | Action | Completion event on `/aux/status` |
|---|---|---|
| `LIFT <mm>` | Lift to absolute height in mm | `EVT LIFT DONE` |
| `PICK` | Lift to fixed `PICK_LIFT_MM` (Config.h) | `EVT LIFT DONE` |
| `DROP` | Lift to fixed `DROP_LIFT_MM` (Config.h) | `EVT LIFT DONE` |
| `STEP EXT` | Extend carriage to max limit | `EVT STEP DONE` |
| `STEP RET` | Retract carriage to home limit | `EVT STEP DONE` |
| `PUMP ON` | Engage vacuum | `EVT PUMP ON` |
| `PUMP OFF` | Release vacuum | `EVT PUMP OFF` |
| `STOP` | Halt drive + lift + stepper immediately | — |

> **Pass:** every command prints its matching `EVT` on `/aux/status`. If a command hangs a
> consumer (e.g. the coordinator), it's waiting for an `EVT` that never came → firmware
> issue or bridge down.

---

## 3. Drive wheels + odometry + IMU  [Jetson]

`serial_bridge_node` also owns the drive motors. With the bridge running (§2b):

### 3a. Check the sensors are alive
```bash
ros2 topic echo /wheel/odometry --once      # encoder odometry (nav_msgs/Odometry)
ros2 topic echo /imu/data --once            # BNO055 heading (sensor_msgs/Imu)
ros2 topic hz /wheel/odometry               # should be ~20 Hz
```

### 3b. Nudge the wheels directly (wheels off the ground first!)
```bash
# forward at 0.1 m/s for a moment, then STOP with zeros
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.1}, angular: {z: 0.0}}"
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.0}}"

# rotate in place
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist \
  "{linear: {x: 0.0}, angular: {z: 0.3}}"
```
**Pass:** wheels turn in the commanded direction and `/wheel/odometry` x (or yaw) moves the
right way. Wrong direction → firmware/serial_bridge polarity params
(`flip_drive_direction`, `ticks_per_rev` 1000, `wheel_radius` 0.0625, `wheel_base` 0.65).

### 3c. Keyboard teleop  [Laptop or Jetson]
```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args -r /cmd_vel:=/cmd_vel_joy
```
Remapped to `cmd_vel_joy` so it feeds **twist_mux at priority 100** — a human always
overrides Nav2. (Drive the robot around; `i/j/k/l`, `k` to stop.)

---

## 4. LiDAR + laser filter  [Jetson]

Brought up inside `robot_navigation.launch.py` (§5), but you can verify the scan alone:
```bash
ros2 topic hz /scan          # filtered scan that Nav2/SLAM consume (~10 Hz)
ros2 topic echo /scan --once
ros2 topic hz /scan_raw      # raw lidar before the chassis box-filter
```
The `laser_filter` node drops the scissor-lift pillars from `/scan_raw` → publishes `/scan`.
Empty `/scan` → check the lidar is powered and `/scan_raw` is publishing.

---

## 5. Navigation — Nav2 + AMCL + RViz

The whole robot + navigation stack is one launch. It starts robot_state_publisher (TF),
`serial_bridge`, EKF, LiDAR + laser_filter, AMCL (map_server), Nav2, and **twist_mux**.

### 5a. Bring it up  [Jetson]
```bash
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=30
ros2 launch amr_bringup robot_navigation.launch.py
```
Verify:
```bash
ros2 topic echo /wheel/odometry --once      # encoders alive
ros2 topic echo /imu/data --once            # IMU alive
ros2 topic list | grep -E "scan|aux|cmd_vel|amcl"
ros2 node list                              # amcl, controller_server, planner_server, bt_navigator, twist_mux...
```

### 5b. RViz — set the pose and click goals  [Laptop]
```bash
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=30      # SAME number as the Jetson
rviz2 -d ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/rviz/navigation.rviz
```
1. **"2D Pose Estimate"** → click + drag where the robot actually is → wait for the AMCL
   particle cloud to converge. **Do not skip — Nav2 drives to nonsense if AMCL isn't localized.**
2. **"Nav2 Goal"** → click a destination → the robot plans and drives.

> Prefer to launch RViz on the Jetson too? `ros2 launch amr_bringup robot_navigation.launch.py launch_rviz:=true`

### 5c. Read the current pose (for surveying waypoints)
```bash
ros2 topic echo /amcl_pose --once           # position.x/y + orientation quaternion
```

### 5d. Named-waypoint scripts  [Laptop, stack running + localized]
```bash
ros2 run amr_navigation waypoint_saver.py shelf_A          # save current pose as "shelf_A"
ros2 run amr_navigation waypoint_navigator.py shelf_A      # drive to one saved waypoint
ros2 run amr_navigation waypoint_navigator.py --list       # list saved waypoints
ros2 run amr_navigation mission_runner.py shelf_A drop_off home   # tour several, pausing at each
```
Waypoints live in `ros2_ws/src/amr_navigation/config/waypoints.yaml`.

### twist_mux priorities (who wins `/cmd_vel`)
| Input topic | Source | Priority |
|---|---|---|
| `cmd_vel_joy` | teleop / joystick | 100 (highest) |
| `cmd_vel_vision` | vision cup-centring | 50 |
| `cmd_vel_nav` | Nav2 | 10 (lowest) |

---

## 6. SLAM — build a new map  [Jetson]

Only when you need to (re)map the warehouse. Skip if `warehouse_map.pgm` is already good.
```bash
source /opt/ros/humble/setup.bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=30
ros2 launch amr_bringup robot_slam.launch.py
```
Drive around slowly with teleop (§3c) to fill the map in RViz, then save it:
```bash
ros2 run nav2_map_server map_saver_cli -f ~/AMR-Warehouse-System/ros2_ws/src/amr_navigation/maps/warehouse_map
```

---

## 7. MQTT + web dashboard

Two topics only: `amr/status` (robot→dashboard, every 3 s) and `amr/orders` (dashboard→robot).

### 7a. Broker  [Jetson]
```bash
sudo systemctl start mosquitto
systemctl is-active mosquitto          # must print: active
hostname -I                            # note the FIRST IP for the laptop
```
First-time only: allow LAN connections —
```bash
sudo tee /etc/mosquitto/conf.d/amr.conf >/dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF
sudo systemctl restart mosquitto
```

### 7b. Bridge  [Jetson]
```bash
cd ~/AMR-Warehouse-System/ros2_ws && source install/setup.bash
ros2 run amr_vision mqtt_bridge
```
Healthy: `mqtt_bridge up — broker localhost:1883` then `[MQTT] Connected — subscribed to amr/orders`.

### 7c. Dashboard  [Laptop]
```bash
MQTT_BROKER=<jetson-ip> python3 app.py          # Linux/Mac, from web_app/
# PowerShell:  $env:MQTT_BROKER="<jetson-ip>";  python app.py
```
Open <http://localhost:5000> → should show **Robot Online**.

### 7d. Step-by-step MQTT tests (stop at first failure)
```bash
# 1. broker alive + window into all traffic (Jetson) — leave running
mosquitto_sub -h localhost -t 'amr/#' -v

# 2. laptop can reach broker (Laptop)
python -c "import socket; s=socket.socket(); s.settimeout(3); print('reachable' if s.connect_ex(('<jetson-ip>',1883))==0 else 'BLOCKED')"

# 3. bridge heartbeat: watch window #1 → amr/status every 3 s

# 4. fake a robot status → dashboard should flip to ALIGNING
mosquitto_pub -h <jetson-ip> -t 'amr/status' \
  -m '{"state":"ALIGNING","vision_stage":"X","current_order":"SHELF-A3","battery":null}'

# 5. press PICK on dashboard (or fake it) → bridge logs "→ /mission/start"
mosquitto_pub -h <jetson-ip> -t 'amr/orders' \
  -m '{"command":"PICK","shelf_id":"SHELF-A3","order_id":"t1"}'
ros2 topic echo /mission/start          # confirm ROS received it
```
Full MQTT detail + troubleshooting table: `docs/MQTT_GUIDE.md`.

---

## 8. Coordinator + full mission

The coordinator is the mission FSM: it drives Nav2, asks vision, and sequences the aux
hardware, waiting for each `EVT`/result before the next step.

### 8a. Test the mission WITHOUT real vision — the stub  [Jetson]
Runs the entire Nav2 → lift → grip → drop → home sequence using a fake vision node that
speaks the exact same contract (drop-in replacement).
```bash
ros2 run amr_coordinator vision_stub
# force failure paths:
ros2 run amr_coordinator vision_stub --ros-args -p fail_shelf:=true
ros2 run amr_coordinator vision_stub --ros-args -p fail_box:=true -p fake_sku:="SKU-TEST-01"
```
Run this **instead of** the real `vision_node` when you want to exercise the coordinator
before the camera is ready.

### 8b. Start the coordinator with the REAL surveyed poses  [Jetson]
Poses are `[x, y, yaw_deg]`. The defaults are placeholders — survey them with §5c/§5d first.
```bash
ros2 run amr_coordinator coordinator_node --ros-args \
  -p shelf_a:="[1.85, 0.42, 0.0]" \
  -p dropoff:="[0.10, 2.30, 90.0]" \
  -p home:="[0.0, 0.0, 0.0]" \
  -p lift_down_mm:=0
```
Other params: `nav_timeout` 180, `lift_timeout` 30, `step_timeout` 20, `pump_timeout` 5,
`vision_timeout` 30, `auto_start` false. Healthy: `amr_coordinator ready.`

### 8c. Trigger the mission
```bash
ros2 topic pub --once /mission/start std_msgs/msg/Empty "{}"
```
…or press **PICK** on the dashboard (mqtt_bridge converts it to `/mission/start`).

### 8d. Watch it run (separate terminals)
```bash
ros2 topic echo /aux/command        # LIFT / STEP / PUMP traffic out
ros2 topic echo /aux/status         # EVT events back from firmware
ros2 topic echo /vision/request     # SHELF_QR / BOX_QR asks
ros2 topic echo /vision/result      # OK <sku> / FAIL
```
Mission sequence: nav→shelf_a → `SHELF_QR` → `LIFT 200` → `BOX_QR`(centre) → `STEP EXT`
→ `PUMP ON` → `STEP RET` → `LIFT 0` → nav→dropoff → `DROP`,`STEP EXT`,`PUMP OFF`,`STEP RET`,`LIFT 0`
→ nav→home. Any timeout or `EVT FAULT` → coordinator aborts and sends `STOP`.

---

## 9. Full-stack bring-up order (test day)

Bring up bottom-up; verify each with the section above before starting the next.

| # | What | Where | Command |
|---|---|---|---|
| 1 | MQTT broker | Jetson | `sudo systemctl start mosquitto` |
| 2 | Robot + Nav2 (incl. serial_bridge, EKF, LiDAR, AMCL, twist_mux) | Jetson | `ros2 launch amr_bringup robot_navigation.launch.py` |
| 3 | Localize in RViz (**2D Pose Estimate**) | Laptop | `rviz2 -d .../amr_navigation/rviz/navigation.rviz` |
| 4 | Vision (`DEPTH_ENABLED=0`) | Jetson | `ros2 run amr_vision vision_node` |
| 5 | MQTT bridge | Jetson | `ros2 run amr_vision mqtt_bridge` |
| 6 | Dashboard | Laptop | `MQTT_BROKER=<jetson-ip> python3 app.py` |
| 7 | Coordinator (real poses) | Jetson | `ros2 run amr_coordinator coordinator_node --ros-args -p shelf_a:=... -p dropoff:=... -p home:=...` |
| 8 | Start mission | Either | `ros2 topic pub --once /mission/start std_msgs/msg/Empty "{}"` |

---

## 10. Topic / interface cheat-sheet

| Topic | Type | Publisher → Subscriber |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | twist_mux → serial_bridge (drive) |
| `/cmd_vel_joy` | `geometry_msgs/Twist` | teleop → twist_mux (prio 100) |
| `/cmd_vel_vision` | `geometry_msgs/Twist` | vision → twist_mux (prio 50) |
| `/cmd_vel_nav` | `geometry_msgs/Twist` | Nav2 → twist_mux (prio 10) |
| `/wheel/odometry` | `nav_msgs/Odometry` | serial_bridge → EKF |
| `/imu/data` | `sensor_msgs/Imu` | serial_bridge → EKF |
| `/scan` / `/scan_raw` | `sensor_msgs/LaserScan` | laser_filter / lidar → Nav2, SLAM |
| `/aux/command` | `std_msgs/String` | coordinator → serial_bridge → Teensy |
| `/aux/status` | `std_msgs/String` | serial_bridge (`EVT …`) → coordinator |
| `/vision/request` | `std_msgs/String` | coordinator → vision (`SHELF_QR`\|`BOX_QR`) |
| `/vision/result` | `std_msgs/String` | vision → coordinator (`OK <sku>`\|`FAIL`) |
| `/mission/start` | `std_msgs/Empty` | dashboard/you → coordinator |
| `/amcl_pose` | `geometry_msgs/PoseWithCovarianceStamped` | AMCL |
| `amr/status` | MQTT JSON | mqtt_bridge → dashboard (3 s heartbeat) |
| `amr/orders` | MQTT JSON | dashboard → mqtt_bridge (PICK/STOP) |

**Related docs:** `docs/RUN_full_scenario.md` (test-day narrative), `docs/TEST_RUNBOOK_vision.md`
(vision deep-dive), `docs/MQTT_GUIDE.md` (MQTT from scratch),
`docs/waypoint_navigation_guide.md`, `docs/slam_mapping.md`.
