# Vision hand-off — put the vision pipeline on ROS + move to the Jetson

**To:** Abdullah   **From:** Nathalie   **Your branch:** `abdalla-vision-branch` (apply these changes there, then we merge)

## The one thing that changes (and why it helps you)
Right now `teensy_comm.py` opens the serial port directly (`COM3` / `/dev/ttyACM0`). That is exactly
what makes moving to the Jetson painful — it's hard-wired to one machine's port. On the integrated
robot **only one program is allowed to open the serial port** (`serial_bridge_node`, which drives
the wheels). So two programs opening `/dev/ttyACM0` isn't allowed.

**Fix:** your vision code stops touching serial and instead **publishes a ROS string**. Same code
runs on your PC and on the Jetson unchanged — ROS doesn't care which machine a node is on. Moving
PC → Jetson becomes "install the package + plug in the camera," not a rewrite.

Your **YOLO models, weights, and all detection code stay exactly as they are.** This is purely about
how the *output* leaves your node.

## Your new role in the system
The mission **coordinator** (my node) is now the boss of the sequence — it owns driving to the
shelf, raising the lift, gripping, and the drop-off. **Vision no longer sequences lift/grip.** Your
node becomes a *service* the coordinator asks two questions:

```
Coordinator → you   on /vision/request  (std_msgs/String):  "SHELF_QR"  or  "BOX_QR"
You → coordinator   on /vision/result   (std_msgs/String):  "OK <sku>"  or  "FAIL"
```

- On **`SHELF_QR`**: detect/confirm the shelf QR → reply `OK <id>` or `FAIL`.
- On **`BOX_QR`**: confirm the box QR **and centre the suction cup**, streaming your servo
  corrections to `/aux/command` as `SERVO <deg>` (10 Hz, like your `SERVO_SEND_HZ`), then reply
  `OK <sku>` once centred.

So the only command vision still sends to the Teensy is **`SERVO`**. `LIFT_UP`, `APPROACH`, `GRIP`,
`STOP` are the coordinator's job now — you can delete those calls from your state machine.

---

## Change 1 — replace `teensy_comm.py` (transport only; API kept)
Swap the raw-serial guts for a tiny ROS publisher to `/aux/command`. Public methods keep their
names and `dry_run` still just prints, so nothing else in your code needs editing.

```python
"""
teensy_comm.py — vision → robot command transport (ROS 2 version)

No longer opens a serial port. Publishes std_msgs/String to /aux/command,
which serial_bridge_node (the single serial owner) forwards to the Teensy.
Public API is unchanged so the rest of the vision pipeline is untouched.
"""

from std_msgs.msg import String


class TeensyComm:
    def __init__(self, node=None, port: str = "", baud: int = 0, dry_run: bool = False):
        """
        node:    an rclpy Node to publish through (pass your vision node's self).
                 If None and not dry_run, a private node is created.
        port/baud: accepted but ignored — kept so old call sites don't break.
        dry_run: if True, print commands instead of publishing.
        """
        self._dry_run = dry_run
        self._pub = None
        if dry_run:
            print("[TeensyComm] dry_run — commands printed, not published")
            return

        if node is None:
            import rclpy
            from rclpy.node import Node
            if not rclpy.ok():
                rclpy.init()
            node = Node("teensy_comm")
        self._pub = node.create_publisher(String, "/aux/command", 10)
        print("[TeensyComm] publishing to /aux/command")

    # ── Only SERVO is still vision's job; the rest are coordinator-owned now ──
    def send_servo(self, correction: float):
        self._send(f"SERVO {correction:.4f}")

    def send_stop(self):
        self._send("STOP")

    # Kept for backward compatibility / manual bring-up, but the coordinator
    # normally issues these. They map onto the shared wire protocol:
    def send_lift_up(self, mm: int = 200): self._send(f"LIFT {mm}")
    def send_approach(self, distance_mm: int): self._send(f"APPROACH {distance_mm}")
    def send_grip(self): self._send("PUMP ON")

    def close(self):
        pass  # nothing to release — no serial handle

    def _send(self, command: str):
        if self._dry_run:
            print(f"[TeensyComm DRY-RUN] >> {command}")
            return
        self._pub.publish(String(data=command))

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
```

> Because vision must be a ROS node to publish, pass your node in: `TeensyComm(node=self)` from
> inside your vision node. If you keep `vision_main.py` as a plain script for PC testing, run it
> with `dry_run=True` and it behaves exactly like before.

## Change 2 — add the request/response glue
Wrap your existing detection + servo code behind the two topics. This is the only new node logic —
your detectors (`qr_detector`, `box_detector`, `visual_servo`, YOLO) are called unchanged.

```python
# inside your vision rclpy Node __init__:
self._teensy = TeensyComm(node=self)
self.create_subscription(String, "/vision/request", self._on_request, 10)
self._result_pub = self.create_publisher(String, "/vision/result", 10)

def _on_request(self, msg):
    req = msg.data.strip()
    if req == "SHELF_QR":
        sku = self.detect_shelf_qr()                 # your existing QR code
        self._reply(f"OK {sku}" if sku else "FAIL")
    elif req == "BOX_QR":
        if not self.detect_box_qr():                 # your existing box/QR/YOLO code
            self._reply("FAIL"); return
        self.center_cup_with_servo()                 # your visual_servo loop, sending
        self._reply(f"OK {self.last_sku}")           #   self._teensy.send_servo(corr) at 10 Hz

def _reply(self, text):
    self._result_pub.publish(String(data=text))
```

`center_cup_with_servo()` is your current servo loop — just keep calling
`self._teensy.send_servo(correction)`; it now goes out over ROS instead of serial. Reply `OK` when
your pixel error is under threshold.

## Change 3 — register the node
In `setup.py` add a console script for the vision node (e.g. `vision_node = amr_vision.vision_node:main`)
and add `std_msgs`, `rclpy` to `package.xml` deps.

---

## Testing on your PC (no robot, no camera-to-Teensy)
```bash
colcon build --packages-select amr_vision && source install/setup.bash
ros2 run amr_vision vision_node            # real detectors, publishing to ROS

# in another terminal, pretend to be the coordinator:
ros2 topic pub --once /vision/request std_msgs/msg/String "{data: 'BOX_QR'}"
ros2 topic echo /vision/result             # expect: OK <sku>
ros2 topic echo /aux/command               # watch your SERVO stream
```
You can test the whole thing with the coordinator + my `vision_stub` too — but the point of your
node is to *replace* the stub. Same topics, so it's a drop-in swap.

## Deploying to the Jetson (this is the part that takes time — start early, it's independent)
The ROS contract means none of your integration depends on this finishing, so do it in parallel:
1. **Copy your trained weights (`.pt`) over unchanged** — the model is fine as-is.
2. The slow part is the runtime: install a **JetPack-matched PyTorch/torchvision** build (don't
   `pip install torch` blindly — use NVIDIA's Jetson wheels or the Ultralytics Jetson guide).
3. For real-time FPS, **export YOLO to TensorRT** (`yolo export format=engine`) and load the
   `.engine` on the Jetson. This is usually the difference between ~5 fps and ~30 fps.
4. Camera: your `config.py` already auto-detects Jetson (`IS_JETSON`) and sets `/dev/ttyACM0`,
   OpenNI2 path, and headless display — good. Just verify the Astra Pro enumerates on the Jetson.
5. `usermod -aG dialout $USER` is **no longer needed for vision** (you don't open serial anymore) —
   only `serial_bridge_node` needs port permission.

When your node is ready, we launch it instead of `vision_stub` and the mission runs on the real
camera. Ping me if `detect_shelf_qr()` / `detect_box_qr()` need a different request name or should
return richer data than a SKU string.
