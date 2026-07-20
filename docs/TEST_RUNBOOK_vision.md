# Vision — Test Day Run-book (Abdalla)

Everything you need at the robot, in order. Vision runs on the **Jetson** (the camera is there).
Branch: `feature/system-integration`.

---

## 0. What vision provides (the contract)

The coordinator asks two questions; vision answers. Nothing else.

```
coordinator -> vision   /vision/request  (std_msgs/String):  "SHELF_QR" | "BOX_QR"
vision -> coordinator   /vision/result   (std_msgs/String):  "OK <sku>" | "FAIL"
```

- **SHELF_QR** — read the shelf QR, reply `OK <id>`.
- **BOX_QR** — read the box QR **and centre the cup** (rotates the robot via `/cmd_vel`), reply `OK <sku>`.

Vision **never** touches the serial port and **never** sends LIFT/STEP/PUMP/STOP — those are the
coordinator's. Vision's only motion output is `/cmd_vel` during BOX_QR centring.

**Depth is OFF (`DEPTH_ENABLED=0`) and that is fine** — the mission never uses vision's depth.
Only the (unused) Stage-2 approach-distance is disabled.

---

## 1. Start vision on the Jetson

```bash
cd ~/AMR-Warehouse-System/ros2_ws
git pull
source install/setup.bash
export DEPTH_ENABLED=0
ros2 run amr_vision vision_node
```

Healthy startup looks like:

```
[vision_node]: Loading model: .../src/amr_vision/models/best.pt
[vision_node]: Opening camera...
[AstraCamera] DEPTH_ENABLED=0 — skipping OpenNI2, RGB-only mode.
[vision_node]: Ready — waiting on /vision/request (SHELF_QR | BOX_QR)
```

> If your terminal mangles pasted commands (stray `~`), type once: `bind 'set enable-bracketed-paste off'`

---

## 2. Self-test before joining the full run (2 min)

Second terminal on the Jetson:

```bash
cd ~/AMR-Warehouse-System/ros2_ws
source install/setup.bash

ros2 topic echo /vision/result &
# hold the SHELF QR to the camera:
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'SHELF_QR'}"
```

Expect `data: "OK <shelf text>"`.

Then the box + centring (robot must be free to rotate!):

```bash
ros2 topic echo /cmd_vel &
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
```

Expect `angular.z` values, then `OK <sku>`.

Camera-only sanity check (no ROS):

```bash
cd ~/AMR-Warehouse-System/ros2_ws/src/amr_vision
export DEPTH_ENABLED=0
python3 scripts/live_qr_test.py
```

---

## 3. Troubleshooting (most likely first)

### 3.1 Robot rotates the WRONG WAY during BOX_QR  ← most likely issue
Centring diverges and times out → `FAIL`.

**Fix (10 seconds, no rebuild — the build is `--symlink-install`):**
Edit `ros2_ws/src/amr_vision/amr_vision/vision_node.py`:

```python
INVERT_TURN = True      # was False
```
Then **Ctrl+C the node and restart it**. No `colcon build` needed.

### 3.2 Rotation too fast / overshoots / jerky
Same file, then restart the node:

```python
MAX_TURN_RATE    = 0.3   # was 0.5  — slower
ANCHOR_SMOOTHING = 0.3   # was 0.5  — smoother (laggier)
```

### 3.3 Stalls just short of centre (wheels don't move on small corrections)
```python
MIN_TURN_RATE = 0.05     # was 0.0 — overcomes stiction
```

### 3.4 `FAIL` on SHELF_QR / BOX_QR (can't read the code)
- Get the QR **bigger in frame**, flat, well lit, hold steady.
- Verify decoding independently with `scripts/live_qr_test.py`.
- If it needs longer, raise in `vision_node.py`: `SHELF_QR_TIMEOUT` / `BOX_QR_TIMEOUT`.
  **Keep `BOX_QR_TIMEOUT + CENTER_TIMEOUT` under the coordinator's `vision_timeout` (default 30 s)**
  or the coordinator aborts mid-centre. If you need more, ask Nathalie to raise `vision_timeout`.

### 3.5 `FileNotFoundError: best.pt`
```bash
export AMR_MODEL_PATH=~/AMR-Warehouse-System/ros2_ws/src/amr_vision/models/best.pt
```
(`best.pt` is gitignored — it must exist on the Jetson; it is not pulled by git.)

### 3.6 Camera segfault / `USB transfer timeout`
- Make sure `export DEPTH_ENABLED=0` is set **in that terminal**.
- Depth needs a **powered USB hub** (the IR projector browns out on chained/passive hubs).
  RGB alone is enough for the whole mission.

### 3.7 Nothing happens when the coordinator asks
```bash
ros2 topic list | grep vision      # /vision/request and /vision/result present?
ros2 node list                     # /vision_node running?
```
Across machines: same network **and same `ROS_DOMAIN_ID`** on Jetson + laptop.

---

## 4. Full-stack bring-up order (with the team)

Bring up bottom-up; verify each before the next.

| # | Node | Owner |
|---|------|-------|
| 1 | `mosquitto` broker (`sudo systemctl start mosquitto`) | Abdalla |
| 2 | `ros2 run amr_hardware serial_bridge_node` | Zahra / HW |
| 3 | Nav2 + map (bringup launch) | Nathalie |
| 4 | `ros2 run amr_vision vision_node` (`DEPTH_ENABLED=0`) | **Abdalla** |
| 5 | `ros2 run amr_vision mqtt_bridge` | Abdalla |
| 6 | `ros2 run amr_coordinator coordinator_node` | Nathalie |

Trigger the mission (or press PICK on the dashboard):

```bash
ros2 topic pub --once /mission/start std_msgs/msg/Empty "{}"
```

**Prerequisites to confirm with the team:**
- Surveyed map + real `shelf_a` / `dropoff` / `home` poses as coordinator params.
- Teensy flashed with LIFT / STEP / PUMP handling.
  (Centring uses `/cmd_vel`, so firmware `SERVO` support is **not** needed.)

---

## 5. Known limitations to state up front

- **Depth disabled** → approach-distance unavailable. Mission unaffected (it never uses it).
  Fix later with a powered USB hub, then `DEPTH_ENABLED=1` — no code change.
- **Centring is an in-place rotation.** A differential drive can't strafe. Large lateral offsets
  mean Nav2 parked badly — fix the shelf pose, don't compensate with a big turn.
- **Centring direction is untested on hardware** — see 3.1 if it turns the wrong way.
