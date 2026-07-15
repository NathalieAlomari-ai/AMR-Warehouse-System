"""
mqtt_bridge.py
--------------
Bridges the integrated ROS 2 mission to the web dashboard over MQTT.

Why this node exists
────────────────────
vision_node.py answers the coordinator's QR requests but does NOT publish MQTT.
In an integrated mission the robot state lives in the coordinator, so nothing
was publishing amr/status and the dashboard showed "Robot Offline".

This node is fully self-contained (lives entirely in amr_vision, needs no change
to anyone else's node). It:

  1. STATUS (robot → web): watches the ROS topics the coordinator / vision /
     hardware already publish, infers the dashboard state, and publishes
     amr/status so the dashboard shows live activity.
  2. ORDERS (web → robot): turns dashboard PICK/STOP messages on amr/orders into
     ROS triggers (/mission/start, /aux/command "STOP").

Forward-compatible: if the coordinator ever publishes /mission/state
(std_msgs/String) with a dashboard state name, this bridge uses it DIRECTLY and
skips inference — accuracy improves automatically with no bridge change.

    NOTE on inference: without /mission/state the state is derived from observed
    events, so it is approximate (e.g. the return-home leg may read as LIFTING).
    It is good enough for a live dashboard; add /mission/state for exact states.

MQTT contract (matches mqtt_publisher.py and web_app/app.py)
    publish   amr/status   {state, vision_stage, current_order, battery}
    subscribe amr/orders    {command: "PICK"|"STOP", shelf_id, order_id}

ROS wiring
    subscribe /mission/state  (std_msgs/String, optional) — direct state, wins
    subscribe /mission/start  (std_msgs/Empty)  — mission triggered  → NAVIGATING
    subscribe /vision/request (std_msgs/String) — SHELF_QR|BOX_QR → SCANNING QR|ALIGNING
    subscribe /aux/command    (std_msgs/String) — LIFT/STEP/PUMP/STOP → LIFTING/DELIVERING/IDLE
    subscribe /cmd_vel        (geometry_msgs/Twist) — motion keep-alive (no IDLE mid-drive)
    publish   /mission/start  (std_msgs/Empty)  — from dashboard PICK
    publish   /aux/command    (std_msgs/String) — "STOP" from dashboard STOP

Run:     ros2 run amr_vision mqtt_bridge
Broker:  ros param 'broker_host'/'broker_port', default from env
         MQTT_BROKER / MQTT_PORT, else localhost:1883 (broker on the Jetson).
"""

import os
import sys
import time

# Import shim — same reason as vision_node.py: make the flat sibling import
# (mqtt_publisher) resolve under `ros2 run` and as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Empty
from geometry_msgs.msg import Twist

from mqtt_publisher import AMRMqttPublisher

# Republish the current state at least this often. The web app marks the robot
# offline if no amr/status arrives within 10 s, so this heartbeat keeps it live.
HEARTBEAT_S = 3.0

# Flip to IDLE after this long with no motion (/cmd_vel) and no mission events.
# /cmd_vel keeps it alive during Nav2 drives, so this only fires when truly idle.
IDLE_AFTER_S = 8.0


class MqttBridge(Node):

    def __init__(self):
        super().__init__("mqtt_bridge")

        broker = self.declare_parameter(
            "broker_host", os.getenv("MQTT_BROKER", "localhost")
        ).get_parameter_value().string_value
        port = self.declare_parameter(
            "broker_port", int(os.getenv("MQTT_PORT", "1883"))
        ).get_parameter_value().integer_value

        # Distinct client_id so it never collides with vision_main.py's publisher.
        self._mqtt = AMRMqttPublisher(broker_host=broker, broker_port=port,
                                      client_id="amr_mqtt_bridge")
        self._mqtt.on_pick_order = self._on_pick_order
        self._mqtt.on_stop       = self._on_stop

        self._state         = "IDLE"
        self._picked        = False       # True while the robot is carrying a box
        self._direct_mode   = False       # True once /mission/state is ever seen
        self._last_activity = time.time()

        # ROS triggers we SEND (web → robot)
        self._start_pub = self.create_publisher(Empty,  "/mission/start", 10)
        self._aux_pub   = self.create_publisher(String, "/aux/command",   10)

        # ROS state sources we WATCH (robot → web)
        self.create_subscription(String, "/mission/state",  self._on_mission_state,   10)
        self.create_subscription(Empty,  "/mission/start",  self._on_mission_start,   10)
        self.create_subscription(String, "/vision/request", self._on_vision_request,  10)
        self.create_subscription(String, "/aux/command",    self._on_aux_command,     10)
        self.create_subscription(Twist,  "/cmd_vel",        self._on_cmd_vel,         10)

        self.create_timer(HEARTBEAT_S, self._tick)
        self.get_logger().info(f"mqtt_bridge up — broker {broker}:{port}")
        self._set_state("IDLE")

    # ── Incoming MQTT orders (web → robot) ───────────────────────────────────────
    def _on_pick_order(self, shelf_id, order_id):
        self.get_logger().info(
            f"dashboard PICK shelf={shelf_id} id={order_id} → /mission/start")
        if shelf_id:
            self._mqtt.set_current_order(shelf_id)
        self._picked = False
        self._start_pub.publish(Empty())
        self._set_state("NAVIGATING")

    def _on_stop(self):
        self.get_logger().warn("dashboard STOP → /aux/command STOP")
        self._aux_pub.publish(String(data="STOP"))
        self._set_state("IDLE")

    # ── ROS state sources (robot → web) ──────────────────────────────────────────
    def _on_mission_state(self, msg):
        # Coordinator is telling us the exact state — trust it, disable inference.
        self._direct_mode = True
        self._set_state(msg.data.strip().upper())

    def _on_mission_start(self, _msg):
        if self._direct_mode:
            return
        self._picked = False
        self._set_state("NAVIGATING")

    def _on_vision_request(self, msg):
        if self._direct_mode:
            return
        req = msg.data.strip()
        if req == "SHELF_QR":
            self._set_state("SCANNING QR")
        elif req == "BOX_QR":
            self._set_state("ALIGNING")

    def _on_aux_command(self, msg):
        if self._direct_mode:
            return
        cmd = msg.data.strip().upper()
        if cmd.startswith("LIFT"):
            self._set_state("DELIVERING" if self._picked else "LIFTING")
        elif cmd.startswith("STEP"):
            self._set_state("DELIVERING" if (self._picked and "RET" in cmd) else "LIFTING")
        elif cmd == "PUMP ON":
            self._picked = True
            self._set_state("LIFTING")
        elif cmd == "PUMP OFF":
            self._picked = False
            self._set_state("DELIVERING")
        elif cmd == "STOP":
            self._set_state("IDLE")

    def _on_cmd_vel(self, _msg):
        # Robot is moving → keep the mission "alive" so idle-decay doesn't trip
        # during a long Nav2 drive that emits no /aux or /vision events.
        self._last_activity = time.time()

    # ── Helpers ──────────────────────────────────────────────────────────────────
    def _set_state(self, state: str):
        self._last_activity = time.time()
        if state != self._state:
            self._state = state
            self.get_logger().info(f"state → {state}")
        self._mqtt.publish_web_state(state)

    def _tick(self):
        # Idle decay (never in direct mode — there we trust the coordinator).
        if (not self._direct_mode and self._state != "IDLE"
                and time.time() - self._last_activity > IDLE_AFTER_S):
            self._state  = "IDLE"
            self._picked = False
            self.get_logger().info("inactivity → IDLE")
        # Heartbeat so the dashboard keeps showing "connected".
        self._mqtt.publish_web_state(self._state)

    def destroy_node(self):
        try:
            self._mqtt.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MqttBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
