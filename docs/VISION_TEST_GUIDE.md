# Vision Test Guide — camera, QR & cup-centring

Everything to test the vision scenario, from the camera alone up to the full
mission. Vision runs on the **Jetson** (the camera is there). Branch:
`feature/system-integration`.

---

## 0. What vision does (the contract)

The coordinator asks two questions on `/vision/request`; vision answers on
`/vision/result`:

| Request | Vision does | Replies |
|---|---|---|
| `SHELF_QR` | read the shelf QR | `OK <id>` / `FAIL` |
| `BOX_QR`  | read the box QR **and centre the cup** (rotates the robot) | `OK <sku>` / `FAIL` |

- Centring is an **in-place rotation** — there is no cup servo; the robot turns
  so the fixed cup lines up with the box.
- Vision publishes its rotation to **`cmd_vel_vision`**, which `twist_mux` merges
  at **priority 50** (beats Nav2 = 10, yields to joystick = 100). It never opens
  serial and never sends LIFT/STEP/PUMP.
- **Depth is not used by the mission.** Run with `DEPTH_ENABLED=0` (RGB only).

---

## 1. One-time on the Jetson

```bash
cd ~/AMR-Warehouse-System/ros2_ws
git pull
colcon build --packages-select amr_vision amr_navigation --symlink-install
source install/setup.bash
echo 'export DEPTH_ENABLED=0' >> ~/.bashrc && source ~/.bashrc
```
> `--symlink-install` means later `.py` edits take effect on node **restart**, no rebuild.
> If your terminal mangles pasted commands (stray `~`): `bind 'set enable-bracketed-paste off'`.

---

## 2. Test 1 — camera + QR (no ROS, ~30 s)

Prove the camera opens and YOLO decodes both codes. Hold a QR to the camera:
```bash
cd ~/AMR-Warehouse-System/ros2_ws/src/amr_vision
python3 scripts/live_qr_test.py
```
✅ Prints `QR decoded: 'SHELF-A1'` (or your text).
❌ `decoded: ''` = seen but not read → closer / more light / hold flat.
❌ segfault / USB timeout = make sure `DEPTH_ENABLED=0` is set in that terminal.

---

## 3. Test 2 — vision ROS handshake

**Terminal A** (the node):
```bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 run amr_vision vision_node
```
Wait for `Ready — waiting on /vision/request`.

**Terminal B** (act as the coordinator), hold the shelf QR up:
```bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 topic echo /vision/result &
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'SHELF_QR'}"
```
✅ `data: "OK <shelf text>"`.

---

## 4. Test 3 — cup-centring (the rotation) ⚠️ read this

Centring output goes to **`cmd_vel_vision`**, which only reaches the wheels when
`twist_mux` is running. So there are **two ways to test**, and picking the wrong
one is the #1 confusion:

### 4a. Centring on the FULL stack (recommended — real behaviour)
Nav2 + twist_mux must be up (`robot_navigation.launch.py`). Then, with the robot
free to rotate and a box QR in view:
```bash
ros2 topic echo /cmd_vel_vision &     # vision's raw command
ros2 topic echo /cmd_vel &            # what actually reaches the wheels (via twist_mux)
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
```
✅ Box on the **RIGHT** → `angular.z` **negative** → robot turns **right** → box comes to centre → `OK <sku>`.

### 4b. Centring STANDALONE (no Nav2/twist_mux)
Nothing forwards `cmd_vel_vision`, so the robot won't move unless you point vision
straight at `/cmd_vel`:
```bash
ros2 run amr_vision vision_node --ros-args -p cmd_vel_topic:=/cmd_vel
# then, in terminal B:
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
```

### If it rotates the WRONG way
Edit `ros2_ws/src/amr_vision/amr_vision/vision_node.py`:
```python
INVERT_TURN = True      # was False
```
Then **Ctrl+C and restart** the node (no rebuild). Other tuning in the same file:
`MAX_TURN_RATE` (speed, default 0.5), `ANCHOR_SMOOTHING` (0.5 → lower = smoother),
`MIN_TURN_RATE` (raise to ~0.05 if it stalls just short of centre).

---

## 5. Test 4 — the WHOLE vision scenario at once (SHELF then BOX)

With `vision_node` running (full stack for real rotation), run this from a second
terminal. It mimics exactly what the coordinator does, back-to-back:
```bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 topic echo /vision/result &

echo ">> show the SHELF QR now"; sleep 3
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'SHELF_QR'}"
sleep 3
echo ">> show the BOX QR now (robot will rotate to centre)"; sleep 3
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
```
✅ Two `OK …` replies, with a rotation between them. That's the complete vision
half of the mission — if this passes, vision is ready for the full run.

---

## 6. In the full mission

You don't call any of the above during the real run — the **coordinator** sends
`SHELF_QR`/`BOX_QR` automatically. Just have `vision_node` running (with
`DEPTH_ENABLED=0`) alongside the stack, and the dashboard PICK button drives it.
Watch it live:
```bash
ros2 topic echo /vision/request      # what the coordinator asks
ros2 topic echo /vision/result       # OK/FAIL
ros2 topic echo /cmd_vel_vision      # centring rotation
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Robot rotates wrong way on BOX_QR | `INVERT_TURN = True`, restart node |
| Robot doesn't move on BOX_QR | You're standalone without twist_mux → use `-p cmd_vel_topic:=/cmd_vel`, or bring up Nav2 |
| Robot drives **backward** on BOX_QR | Old bug (vision fighting Nav2). Confirm `cmd_vel_topic=/cmd_vel_vision` and twist_mux has the `vision` input (priority 50) |
| `FAIL` on SHELF/BOX | QR bigger/flatter/lit; verify with `scripts/live_qr_test.py`; raise `SHELF_QR_TIMEOUT`/`BOX_QR_TIMEOUT` but keep `BOX_QR_TIMEOUT + CENTER_TIMEOUT < 30 s` |
| Camera segfault / USB transfer timeout | `export DEPTH_ENABLED=0`; depth needs a powered USB hub (mission never uses depth) |
| `FileNotFoundError: best.pt` | `export AMR_MODEL_PATH=~/AMR-Warehouse-System/ros2_ws/src/amr_vision/models/best.pt` |
| Node runs old code after edit | rebuilt without `--symlink-install`, or edited install/ not src/ → rebuild once with `--symlink-install`, then edits need only a restart |

**Golden rule:** `ros2 topic echo /vision/result` in a spare terminal. If `OK`
comes back, detection works and any remaining issue is motion (twist_mux / direction).
