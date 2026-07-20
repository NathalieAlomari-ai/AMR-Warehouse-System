# Full Scenario — Test Day Run Guide

Branch: **`feature/system-integration`** (everything lives here — pull it everywhere).

---

## A. System audit — what's ready

| Part | Owner | Status |
|---|---|---|
| **Firmware** (Teensy) — `LIFT <mm>`, `PICK`, `DROP`, `STEP EXT/RET`, `PUMP ON/OFF`, `STOP` + emits `EVT LIFT DONE` / `EVT STEP DONE` / `EVT PUMP ON/OFF` | Zahra | ✅ on integration |
| **serial_bridge_node** — single serial owner; `/cmd_vel`+`/aux/command` → Teensy; publishes `/wheel/odometry`, `/imu/data`, `/aux/status` | Nathalie | ✅ |
| **SLAM / map / Nav2 / EKF** — `maps/warehouse_map.pgm`, `nav2_params.yaml`, `ekf.yaml`, AMCL, twist_mux | Nathalie | ✅ merged (`feature/slam-setup` has 0 unique commits) |
| **Coordinator** — mission FSM | Nathalie | ✅ |
| **vision_node** — `SHELF_QR`/`BOX_QR` → `OK <sku>`/`FAIL`, centring via `/cmd_vel` | Abdalla | ✅ camera+QR verified on Jetson |
| **mqtt_bridge** — ROS ↔ dashboard | Abdalla | ✅ |
| **Web dashboard** (`web_app/`) | Abdalla | ✅ (added to integration today) |

**Not merged into integration** (hardware experiment branches — verify nothing needed is stranded):
`linear_acc` (9 commits), `stepper_motor_test` (8), `teensy-test-wheels` (5), `claude/features-slam-setup-nhy1c2` (31).
The integration firmware already implements lift/stepper/pump, so these are most likely superseded — **confirm with Zahra**.

---

## B. Prerequisites

- Teensy flashed with `firmware/integration`, connected (`ls /dev/ttyACM*`), user in `dialout`.
- LiDAR + Astra camera plugged in (camera on the Jetson).
- **Real surveyed poses** for `shelf_a` / `dropoff` / `home` (see §D). Defaults in the coordinator are placeholders!
- Everything pulled: `git pull` on Jetson **and** laptop.

---

## C. Startup order (bottom-up — verify each before the next)

### 1. MQTT broker (Jetson)
```bash
sudo systemctl start mosquitto
hostname -I          # note the Jetson IP for the dashboard
```

### 2. Hardware + Navigation (Jetson) — one launch does it all
```bash
cd ~/AMR-Warehouse-System/ros2_ws
git pull && colcon build --symlink-install && source install/setup.bash
ros2 launch amr_bringup robot_navigation.launch.py
```
Starts: robot_state_publisher (TF), **serial_bridge**, **EKF**, LiDAR, **AMCL**, **Nav2**, **twist_mux**.

Verify:
```bash
ros2 topic echo /wheel/odometry --once     # encoders alive
ros2 topic echo /imu/data --once           # IMU alive
ros2 topic list | grep -E "scan|aux|cmd_vel"
```

### 3. Localize the robot on the map  ← **do not skip**
On a machine with a display:
```bash
ros2 launch amr_bringup robot_navigation.launch.py launch_rviz:=true
```
In RViz: **"2D Pose Estimate"** → click+drag where the robot actually is → wait for the AMCL cloud to converge.
**Nav2 will drive to nonsense if AMCL isn't localized.**

### 4. Vision (Jetson)
```bash
cd ~/AMR-Warehouse-System/ros2_ws && source install/setup.bash
export DEPTH_ENABLED=0
ros2 run amr_vision vision_node
```
Healthy: `Ready — waiting on /vision/request (SHELF_QR | BOX_QR)`

### 5. Dashboard bridge (Jetson)
```bash
ros2 run amr_vision mqtt_bridge
```

### 6. Dashboard web app (laptop)
```bash
cd ~/AMR-Warehouse-System/web_app
MQTT_BROKER=<jetson-ip> python3 app.py
# open http://localhost:5000
```
Should show **Robot Online** (the bridge heartbeats every 3 s).

### 7. Coordinator — with the REAL poses
```bash
ros2 run amr_coordinator coordinator_node --ros-args \
  -p shelf_a:="[1.85, 0.42, 0.0]" \
  -p dropoff:="[0.10, 2.30, 90.0]" \
  -p home:="[0.0, 0.0, 0.0]" \
  -p shelf_height_mm:=200 \
  -p drop_height_mm:=120
```
Healthy: `amr_coordinator ready.`

---

## D. Getting the real poses (do before §C.7)

With the map loaded and AMCL localized, drive the robot to each spot and read its pose:
```bash
ros2 topic echo /amcl_pose --once
```
Take `position.x`, `position.y`, and convert the quaternion yaw to degrees.
(Or use `amr_navigation/scripts/waypoint_saver.py`.)
Record for: **shelf A**, **dropoff**, **home** → feed into §C.7.

---

## E. Run the mission

```bash
ros2 topic pub --once /mission/start std_msgs/msg/Empty "{}"
```
…or press **PICK** on the dashboard (mqtt_bridge converts it to `/mission/start`).

The coordinator then blocks through this checklist:

| # | Sends | Waits for |
|---|---|---|
| 1 | Nav2 goal → `shelf_a` | arrival |
| 2 | `/vision/request` `SHELF_QR` | `OK <id>` from vision |
| 3 | `/aux/command` `LIFT 200` | `EVT LIFT DONE` |
| 4 | `/vision/request` `BOX_QR` | vision centres cup → `OK <sku>` |
| 5 | `STEP EXT` | `EVT STEP DONE` |
| 6 | `PUMP ON` | `EVT PUMP ON` |
| 7 | `STEP RET` | `EVT STEP DONE` |
| 8 | `LIFT 0` | `EVT LIFT DONE` |
| 9 | Nav2 goal → `dropoff` | arrival |
| 10 | `LIFT 120`, `STEP EXT`, `PUMP OFF`, `STEP RET`, `LIFT 0` | each `EVT` |
| 11 | Nav2 goal → `home` | arrival |

Any timeout or `EVT FAULT` → coordinator aborts and sends `STOP`.

Watch it live:
```bash
ros2 topic echo /aux/command        # lift/step/pump traffic
ros2 topic echo /aux/status         # EVT events from firmware
ros2 topic echo /vision/result      # OK/FAIL
```

---

## F. Troubleshooting

### F.1 Robot rotates the WRONG WAY during BOX_QR  ← most likely vision issue
Edit `ros2_ws/src/amr_vision/amr_vision/vision_node.py`: `INVERT_TURN = True`, then **restart the node**.
No rebuild needed (`--symlink-install`).
Too fast/jerky → `MAX_TURN_RATE = 0.3`, `ANCHOR_SMOOTHING = 0.3`. Stalls short of centre → `MIN_TURN_RATE = 0.05`.

### F.2 ⚠️ Robot doesn't move at all during BOX_QR centring — **twist_mux conflict**
`twist_mux` **publishes `/cmd_vel`**, and vision publishes there too (vision is *not* a mux input).
It normally works because `cmd_vel_nav` times out 0.5 s after Nav2 finishes and twist_mux goes quiet — but if it fights:
```bash
ros2 topic info /cmd_vel            # >1 publisher = twist_mux + vision
ros2 topic hz /cmd_vel              # is something spamming zeros?
```
**Proper fix (with Nathalie):** add vision as a twist_mux input in `amr_navigation/config/twist_mux.yaml`:
```yaml
      vision:
        topic   : cmd_vel_vision
        timeout : 0.5
        priority: 50        # above nav(10), below joystick(100)
```
then point vision at `cmd_vel_vision`. **Quick test hack:** stop Nav2/twist_mux and re-run BOX_QR alone.

### F.3 Vision replies FAIL
QR bigger/flatter/better lit. Verify decode independently:
```bash
cd ~/AMR-Warehouse-System/ros2_ws/src/amr_vision && python3 scripts/live_qr_test.py
```
Need longer? Raise `SHELF_QR_TIMEOUT`/`BOX_QR_TIMEOUT` — but keep `BOX_QR_TIMEOUT + CENTER_TIMEOUT < 30 s`
(the coordinator's `vision_timeout`) or it aborts mid-centre.

### F.4 Camera segfault / `USB transfer timeout`
`export DEPTH_ENABLED=0` **in that terminal**. Depth needs a powered USB hub — **the mission never uses vision's depth**, so RGB-only is fine.

### F.5 `FileNotFoundError: best.pt`
`best.pt` is gitignored — it must already be on the Jetson.
```bash
export AMR_MODEL_PATH=~/AMR-Warehouse-System/ros2_ws/src/amr_vision/models/best.pt
```

### F.6 Coordinator hangs on a step
It's waiting for an `EVT`. Check `ros2 topic echo /aux/status`. Nothing → firmware isn't sending it (Zahra) or serial_bridge is down.

### F.7 Nodes on different machines can't see each other
Same network **and same `ROS_DOMAIN_ID`** on Jetson + laptop.

### F.8 Dashboard shows Offline
mosquitto running? `MQTT_BROKER` = Jetson IP? `mqtt_bridge` running?
```bash
mosquitto_sub -h <jetson-ip> -t 'amr/status' -v
```

---

## G. Known limitations (state these up front)

- **Depth disabled** → approach-distance unavailable. **Mission unaffected** (never used).
- **Centring = in-place rotation.** Diff-drive can't strafe. Big lateral offset ⇒ Nav2 parked badly — fix the shelf pose, not the turn.
- **Centring direction untested on hardware** — see F.1.
- **Vision publishes `/cmd_vel` directly**, bypassing twist_mux — see F.2.
