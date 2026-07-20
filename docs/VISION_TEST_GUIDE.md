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
- `CENTER_TIMEOUT` is currently **45 s** (a debug value — raised from 15 s while
  we confirm the wheel-command chain end to end). See §7 before running this
  through the real coordinator-driven mission, not just manual testing.

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
one is the #1 confusion — it's exactly what caused "BOX QR confirmed, then times
out every time" on our first robot test.

### 4a. Centring on the FULL stack (recommended — real behaviour)
Nav2 + twist_mux **and serial_bridge** must be up — one launch starts all three:
```bash
ros2 launch amr_bringup robot_navigation.launch.py
```
Then, with the robot free to rotate and a box QR in view, in another terminal:
```bash
ros2 run amr_vision vision_node
```
and a third terminal to trigger it:
```bash
source ~/AMR-Warehouse-System/ros2_ws/install/setup.bash
ros2 topic echo /cmd_vel_vision &     # vision's raw command
ros2 topic echo /cmd_vel &            # what actually reaches the wheels (via twist_mux)
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
```
✅ Box on the **RIGHT** → `angular.z` **negative** → robot turns **right** → box comes to centre → `OK <sku>`.

**Watch `vision_node`'s own terminal** — it now self-diagnoses this exact mistake:
```
[WARN] no subscribers on /cmd_vel_vision — rotation commands will go nowhere and
       this WILL time out. Launch 'robot_navigation.launch.py' (starts twist_mux),
       or override with --ros-args -p cmd_vel_topic:=/cmd_vel for a standalone test.
[INFO] centring: FINE (QR) offset=+42px correction=+0.3360 stable=0/10 subs=1
[INFO] centring: FINE (QR) offset=+18px correction=+0.1440 stable=0/10 subs=1
[INFO] centring: FINE (QR) offset=-3px  correction=-0.0240 stable=6/10 subs=1
```
That progress line prints **once a second** during centring — read it like this:

| What you see | Means |
|---|---|
| `subs=0` | Nothing is subscribed to `cmd_vel_vision` → twist_mux isn't running → §4a fix above, or use §4b |
| `subs≥1`, offset **static/growing**, `stable` stuck at 0 | Command is being sent and something IS subscribed, but the robot doesn't visibly turn → go straight to §7's wheel-command chain check (twist_mux → `/cmd_vel` → serial_bridge → Teensy) |
| `subs≥1`, offset **shrinking**, `stable` climbing | Working — just give it time (up to `CENTER_TIMEOUT`) |
| offset sign flips back and forth, never converges | Likely `INVERT_TURN` wrong, or `MAX_TURN_RATE` too aggressive → see below |

### 4b. Centring STANDALONE (no Nav2/twist_mux)
For a bench test of vision alone, with `serial_bridge_node` already running so
`/cmd_vel` actually reaches the Teensy:
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

Needs the **full stack** (§4a) for the rotation to actually move the robot:
`robot_navigation.launch.py` running, then `vision_node`.

> ⚠️ **`vision_node` MUST already be running and past "Ready" in its own
> terminal before you run the script below.** Skipping this is the single most
> common mistake with this test — you'll get
> `WARNING: topic [/vision/result] does not appear to be published yet` and the
> `ros2 topic pub` will hang forever on `Waiting for at least 1 matching
> subscription(s)...`. Neither is a bug; it just means nothing is listening yet.
> One-line check before you run anything else:
> ```bash
> ros2 node list | grep vision_node
> ```
> If that prints nothing, go start it first (§3) and wait for
> `Ready — waiting on /vision/request` before continuing.

Once confirmed, run this from a **separate** terminal — it mimics exactly what
the coordinator does, back-to-back:
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

## 7. "Wheels not moving, no command received" — the full chain

The rotation command's path is: `vision_node` → `cmd_vel_vision` → `twist_mux`
→ `/cmd_vel` → `serial_bridge_node` → Teensy. Check each link **in order** and
stop at the first failure — that's the fix.

```bash
# 1. Is twist_mux even running?
ros2 node list | grep twist_mux
```
❌ nothing → you only started `vision_node`, not the nav stack. Run:
```bash
ros2 launch amr_bringup robot_navigation.launch.py
```

```bash
# 2. Is twist_mux actually forwarding to /cmd_vel?
ros2 topic echo /cmd_vel
# ...then trigger BOX_QR and watch for Twist messages
```
❌ nothing here even with twist_mux running → check
`ros2_ws/src/amr_navigation/config/twist_mux.yaml` has the `vision:` entry
(priority 50, topic `cmd_vel_vision`), and that `navigation.launch.py` remaps
twist_mux's output to `/cmd_vel` (not left on an internal `cmd_vel_out`).

```bash
# 3. Is serial_bridge running and does it see /cmd_vel?
ros2 node list | grep serial_bridge
ros2 topic info /cmd_vel     # subscriber count should be ≥1 once serial_bridge is up
```
❌ not running → nothing relays the command to the Teensy. It's started by the
same launch as step 1 — if it's still missing, check that launch's log for a crash.

```bash
# 4. Is the Teensy actually connected?
```
Check `serial_bridge_node`'s own startup log:
- `Opened serial port /dev/ttyACM0` ✅
- `Could not open serial port ...` ❌ →
  `ls /dev/ttyACM* /dev/ttyUSB*`, check the USB cable, check you're in the
  `dialout` group, check the Teensy is flashed and powered.

**Most likely culprit:** step 1. `robot_navigation.launch.py` starts twist_mux
**and** serial_bridge together — if that launch wasn't running, both the
centring rotation *and* the wheel relay are simultaneously missing, which
matches "BOX QR confirmed, then times out every time."

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `WARNING: topic [...] does not appear to be published yet`, or `ros2 topic pub` hangs on `Waiting for at least 1 matching subscription(s)...` | `vision_node` isn't running yet. Start it first (§3), wait for `Ready — waiting on /vision/request`, **then** run the test in a separate terminal. Check with `ros2 node list \| grep vision_node`. |
| Robot rotates wrong way on BOX_QR | `INVERT_TURN = True`, restart node |
| Robot doesn't move on BOX_QR, `subs=0` in the log | twist_mux isn't running → §4a, or use §4b's `cmd_vel_topic` override |
| Robot doesn't move on BOX_QR, `subs≥1` in the log | Command IS being sent — walk the chain in §7 (twist_mux → `/cmd_vel` → serial_bridge → Teensy) |
| Robot drives **backward** on BOX_QR | Old bug (vision fighting Nav2). Confirm `cmd_vel_topic=/cmd_vel_vision` and twist_mux has the `vision` input (priority 50) |
| `FAIL` on SHELF/BOX | QR bigger/flatter/lit; verify with `scripts/live_qr_test.py` |
| Testing manually with `CENTER_TIMEOUT` raised above ~18s | Fine for manual `ros2 topic pub` testing. Before running through the **real coordinator-driven mission**, either lower `CENTER_TIMEOUT` back down, or raise the coordinator's own timeout to match: `ros2 run amr_coordinator coordinator_node --ros-args -p vision_timeout:=60.0` — otherwise the coordinator aborts and sends STOP at its default 30s while vision is still trying in the background |
| Camera segfault / USB transfer timeout | `export DEPTH_ENABLED=0`; depth needs a powered USB hub (mission never uses depth) |
| `FileNotFoundError: best.pt` | `export AMR_MODEL_PATH=~/AMR-Warehouse-System/ros2_ws/src/amr_vision/models/best.pt` |
| Node runs old code after edit | rebuilt without `--symlink-install`, or edited install/ not src/ → rebuild once with `--symlink-install`, then edits need only a restart |

**Golden rule:** watch `vision_node`'s own terminal during BOX_QR — the 1 Hz
`centring: ... subs=N` line now tells you directly whether the problem is
detection (offset never appears), motion routing (`subs=0`), or something
downstream of `/cmd_vel` (`subs≥1` but the robot doesn't turn).
