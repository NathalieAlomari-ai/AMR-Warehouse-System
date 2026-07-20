# Navixa AMR — Expo & Defence Guide (Abdalla)

Your three subsystems, explained for presenting and defending:
**1) Battery system · 2) Vision · 3) Software system.**
Read the summary, then the details, then the "Defence Q&A" at the end of each part.

---

## The system in one paragraph

**Navixa** is an autonomous warehouse robot that performs a full pick-and-place
mission from a single dashboard click: it navigates to a shelf, confirms it by
reading a QR with a camera, raises a scissor lift, visually centres a suction
cup on the target box and grips it, drives to a drop-off bay, releases the box,
and returns home — while a live web dashboard mirrors every step. It runs **ROS 2**
on an **NVIDIA Jetson** (vision + high-level control) and a **Teensy 4.1**
(motors, lift, gripper), fused with **LiDAR + IMU + wheel odometry** for SLAM and
**Nav2** navigation.

```
            ┌──────────── Jetson (ROS 2) ────────────┐
 Dashboard  │  coordinator ── vision_node ── mqtt_bridge│   Teensy 4.1
 (Flask/MQTT)│      │            │                  │   │  (firmware)
      ▲──MQTT┼──────┘   Nav2 / SLAM / EKF          │   │  drive PID
      │      │            │                         │   │  scissor lift
      └──────┼──> /mission/start                    │   │  stepper + pump
             └──── /cmd_vel, /aux/command ───────────┼──▶│
   LiDAR + IMU + encoders ─────────────────────────┘   └─ motors/lift/gripper
```

---

# 1) Battery System

**What we used:** two **6S Li-ion** packs — a **6S-3P** and a **6S-2P** — instead
of a single LiPo pack. 6S = 6 cells in series; the "2P/3P" is how many cells are
paralleled to add capacity and current.

**Why two packs (the key design idea):** we **split the power rails**. The larger,
stiffer **6S-3P** feeds the **drive rail** (the two wheel motors — the high-current,
spiky load). The **6S-2P** feeds the **electronics/aux rail** (Jetson, LiDAR,
Teensy, sensors, lift/stepper). This isolation stops motor current spikes from
sagging the voltage on the compute rail — which is exactly what causes a Jetson to
brown out or a USB camera to drop. Separating them keeps vision and navigation
rock-solid while the motors do heavy work.

### Voltage (6S Li-ion)
| State | Per cell | 6S pack |
|---|---|---|
| Full charge | 4.2 V | **25.2 V** |
| Nominal | 3.6 V | **21.6 V** |
| Empty (cut-off) | 3.0 V | **18.0 V** |

6S Li-ion (21.6 V nominal / 25.2 V full) is **drop-in compatible** with the same
6S electronics, BMS and chargers a 6S LiPo would use — same full-charge voltage,
so no redesign of the power electronics.

### Capacity, energy & current — worked example
> **Assumption (state this in the defence):** 18650 cells, **3000 mAh (3.0 Ah)**
> and **10 A** continuous each. *Substitute your actual cell spec — the formulas
> don't change.*

**Formulas**
- Pack capacity (Ah) = cell Ah × (number in parallel, P)
- Pack energy (Wh) = nominal voltage (V) × pack capacity (Ah)
- Pack max current (A) = cell max current × P
- Runtime (h) = pack capacity (Ah) ÷ average current draw (A)

| Pack | Role | Capacity | Energy | Max continuous current |
|---|---|---|---|---|
| **6S-3P** | Drive rail (motors) | 3 × 3.0 = **9.0 Ah** | 21.6 × 9.0 = **194.4 Wh** | 3 × 10 = **30 A** |
| **6S-2P** | Electronics/aux rail | 2 × 3.0 = **6.0 Ah** | 21.6 × 6.0 = **129.6 Wh** | 2 × 10 = **20 A** |
| **Total** | whole robot | 15.0 Ah (as 5P) | **≈ 324 Wh** | — |

**Runtime estimate** (plug in your measured averages):
- Drive rail at, say, ~5 A average → 9.0 Ah ÷ 5 A ≈ **1.8 h** of active driving.
- Aux rail at ~2.5 A average → 6.0 Ah ÷ 2.5 A ≈ **2.4 h**.
- System endurance is set by whichever empties first (drive) → **~1.5–1.8 h** of
  continuous operation — far more than a mission or an expo run needs.

**Head-room check:** motor peaks are ~10–15 A; the 6S-3P delivers 30 A continuous,
so the drive pack runs at **under ~0.5C** — cool, low-stress, long life.

### Why Li-ion (6S-2P/3P) instead of LiPo — the defence argument
| Criterion | Li-ion 18650 (ours) | LiPo pouch | Why it matters for a warehouse robot |
|---|---|---|---|
| **Energy density** | Higher Wh/kg | Lower | More **runtime per kg** — endurance, not burst, is our load profile |
| **Cycle life** | ~500–1000+ cycles | ~200–300 | Charged daily → **lasts years, lower lifetime cost** |
| **Safety / durability** | Rigid steel can, vented, hard to puncture | Soft pouch, swells, puncture/fire risk | A ground robot **bumps things** — cylindrical cells are far safer |
| **Peak C-rate** | Moderate (enough) | Very high | We **don't need** drone-like burst current; motors are modest |
| **Storage tolerance** | Forgiving | Finicky (storage voltage) | Easier to maintain between demos |

**The one-line answer** for the panel: *"A warehouse robot needs endurance,
cycle life and safety, not the burst current LiPo is prized for. Cylindrical
Li-ion gives us more runtime per kg, many more charge cycles, and a mechanically
robust, safer cell — and by splitting a stiff 6S-3P drive pack from a 6S-2P
electronics pack, motor spikes never brown out the Jetson or the camera."*

### Battery — Defence Q&A
- **Q: Why 6S?** → 21.6 V nominal matches our motor driver / buck-converter input
  range and gives good efficiency (higher voltage = lower current for the same
  power = less I²R loss and thinner wiring).
- **Q: Why parallel two different packs (2P vs 3P)?** → They're not paralleled into
  one bus — they feed **separate rails**. The drive rail needs more current and
  benefits from lower internal resistance (3P); the electronics rail needs less,
  so 2P is enough. Isolation protects compute from motor transients.
- **Q: How do you stop over-discharge?** → 6S BMS with per-cell protection and a
  3.0 V/cell cut-off; the low C-rate also keeps cells healthy.
- **Q: Runtime?** → ~1.5–1.8 h active (show the calc above).

---

# 2) Vision

**Hardware:** Orbbec **Astra Pro** depth camera (RGB + IR depth) on the Jetson.
**Model:** a custom-trained **YOLOv8** network (`best.pt`) that detects the target
**box**, **QR code**, and **barcode** classes.

**Vision is a service, not a driver.** It does not run the mission — the
coordinator asks it two questions and it answers:

| Request | What vision does | Reply |
|---|---|---|
| `SHELF_QR` | read the shelf's QR label | `OK <id>` / `FAIL` |
| `BOX_QR` | read the box QR **and centre the suction cup on it** | `OK <sku>` / `FAIL` |

### How QR reading works (and why it's robust)
1. **YOLO localises** the QR region in the frame (fast, works at distance/angle).
2. We **crop + upscale + CLAHE-enhance** that region.
3. **Multi-strategy decode:** OpenCV `QRCodeDetector` first, then `pyzbar` on raw
   and enhanced crops, then OpenCV on the full frame — whichever reads first wins.
4. We require the **same value on several consecutive frames** before trusting it
   (rejects single-frame glitches).

*Why YOLO-then-decode?* Running a decoder on the full 640×480 frame is slow and
unreliable on small/angled codes; localising first makes it fast and robust.

### How cup-centring works (visual servoing)
The suction cup is **fixed** to the robot — there is **no cup servo**. To line it
up with the box we **rotate the whole robot**:
1. Detect the box/QR centre in the image; compute its **horizontal pixel offset**
   from frame centre.
2. A **proportional controller** turns that offset into a rotation speed
   (`angular.z`), smoothed across frames (**EMA**) to kill YOLO jitter, and
   **clamped** so it can never spin fast.
3. Publish to **`cmd_vel_vision`**; **twist_mux** merges it at **priority 50**
   (above Nav2, below the joystick e-stop) so it reaches the wheels without
   fighting navigation.
4. When the box holds centre for several frames → reply `OK`.

*Why rotate, not strafe?* A differential-drive robot **can't move sideways** — the
only way to bring a fixed cup onto the box is a small in-place rotation.

### Robustness we built in
- **RGB-only fallback** (`DEPTH_ENABLED=0`): if the depth sensor can't open (it's
  power-hungry over USB), vision keeps running on RGB — QR reading and centring
  only need RGB. Depth (approach distance) is the only thing lost, and the mission
  doesn't use it.
- **Portable model path** and an **import shim** so it runs identically as a
  script, via `ros2 run`, on the PC or the Jetson.

### Vision — Defence Q&A
- **Q: Why not just decode QR directly?** → Too slow/unreliable full-frame; YOLO
  localises first, then a multi-decoder reads it — fast and robust to angle/lighting.
- **Q: How do you centre without a servo?** → Visual servoing: pixel offset →
  proportional rotation of the whole robot, smoothed and priority-arbitrated.
- **Q: What if the camera loses depth?** → Automatic RGB-only mode; mission
  unaffected because it never uses vision depth.
- **Q: How does vision avoid fighting Nav2 for the wheels?** → It publishes to a
  separate `cmd_vel_vision` topic that twist_mux prioritises over navigation.

---

# 3) Software System

Built on **ROS 2** as a set of cooperating nodes, plus a web layer over **MQTT**.

### The nodes and how they talk
| Node | Role |
|---|---|
| `serial_bridge_node` | **Single owner of the Teensy serial port**; turns `/cmd_vel` into wheel RPM and forwards `/aux/command` (lift/stepper/pump); publishes wheel odometry + IMU |
| EKF (`robot_localization`) | Fuses wheel odometry + IMU → smooth `odom → base_footprint` |
| SLAM / AMCL + **Nav2** | Builds/uses the map, localises, plans and drives via `/cmd_vel` |
| `twist_mux` | Arbitrates the wheel bus: joystick (100) > **vision (50)** > Nav2 (10) |
| **`coordinator_node`** | The mission brain — a state machine that sequences the whole pick-and-place |
| **`vision_node`** | Answers `SHELF_QR` / `BOX_QR`, centres the cup (my part) |
| **`mqtt_bridge`** | Bridges ROS ↔ the web dashboard over MQTT (my part) |
| **Web dashboard** | Flask app: operator clicks PICK, sees live state (my part) |

### The mission (what one dashboard click triggers)
```
Dashboard PICK ─MQTT(amr/orders)─▶ mqtt_bridge ─▶ /mission/start ─▶ coordinator:
  1  navigate → shelf_a
  2  ask vision SHELF_QR         → OK
  3  PICK (raise lift)           → wait EVT LIFT DONE
  4  ask vision BOX_QR           → vision rotates to centre cup → OK
  5  STEP EXT → PUMP ON → STEP RET   (extend, grip, retract)
  6  lower lift → navigate → dropoff
  7  DROP → STEP EXT → PUMP OFF → STEP RET → lower lift
  8  navigate → home             → MISSION COMPLETE
```
The coordinator **blocks on an event after every step** (`EVT LIFT DONE`,
`OK <sku>`, arrival), so it never runs ahead of the hardware; any timeout or
firmware `EVT FAULT` aborts safely with a `STOP`.

### The web + MQTT layer (my part)
- **MQTT = the post office.** Robot and dashboard never talk directly; they publish
  and subscribe to a broker (`mosquitto`). Two topics: `amr/status` (robot→web,
  every 3 s heartbeat) and `amr/orders` (web→robot).
- **`mqtt_bridge`** translates: dashboard **PICK** → `/mission/start`; and it
  **infers the live state** from ROS activity (`/vision/request`, `/aux/command`,
  `/cmd_vel`) → publishes `amr/status` so the dashboard pipeline animates.
- **Dashboard** is a **Flask** app (login, order form, live pipeline view),
  **deployed publicly on Vercel** (`navixaa.vercel.app`) for the showcase, and run
  locally next to the robot for the live demo.

### Key software design decisions (great defence material)
- **Single serial owner** → only `serial_bridge` touches the port, so nothing
  collides on the wire.
- **Decoupled vision service** → the coordinator doesn't care *how* vision works,
  only the `OK`/`FAIL` answer; we swapped a stub for the real node with zero
  coordinator changes.
- **twist_mux arbitration** → three sources safely share the wheels by priority.
- **MQTT bridge** → the web UI is fully decoupled from ROS; the dashboard can't
  crash the robot and vice-versa.
- **Graceful degradation** → RGB-only vision, non-blocking MQTT, auto-reconnect.

### Software — Defence Q&A
- **Q: Why ROS 2?** → Standard robotics middleware: named topics/actions, easy
  multi-node/multi-machine, and off-the-shelf Nav2/SLAM/EKF we integrate rather
  than reinvent.
- **Q: Why MQTT for the dashboard instead of ROS?** → Lightweight, web-friendly,
  and decouples a browser UI from the ROS graph; the bridge is the only link.
- **Q: What starts the whole mission?** → One `/mission/start` message (from the
  dashboard PICK); the coordinator FSM does the rest.
- **Q: What if a step fails?** → Every step waits for its completion event; a
  timeout or `EVT FAULT` aborts the mission and stops the hardware.
- **Q: How is the dashboard live?** → `mqtt_bridge` heartbeats `amr/status` every
  3 s; the dashboard marks the robot offline if it hears nothing for 10 s.

---

## 60-second elevator pitch (memorise this)

> "Navixa is an autonomous warehouse robot. An operator clicks one button on our
> web dashboard; that order goes over MQTT to the robot, which navigates to the
> shelf, reads a QR to confirm it, raises a lift, uses the camera to visually
> centre a suction cup on the box and grips it, drives to the drop-off, releases
> it, and returns home — all sequenced by a ROS 2 mission coordinator and shown
> live on the dashboard. My three parts were the **power system** (split Li-ion
> 6S packs for endurance, safety and a clean compute rail), the **vision**
> (YOLOv8 QR reading and visual-servo cup-centring), and the **software** (the
> web dashboard and the MQTT bridge that ties it all to ROS)."

---

*Numbers in the battery section assume 3000 mAh / 10 A cells — replace with your
actual cell datasheet values before the defence; the formulas stay the same.*
