"""
mqtt_publisher.py
-----------------
MQTT bridge between the vision pipeline (Jetson) and the web dashboard (Flask).

Topics — matches web_app/app.py exactly:
    amr/status   (vision -> web)   — combined robot state published every transition
    amr/orders   (web -> vision)   — pick orders from the operator dashboard

Status payload (what app.py on_message() reads):
    {
        "state":         "SCANNING QR",   <- shown on dashboard pipeline
        "vision_stage":  "STAGE_1",       <- raw stage name for debugging
        "current_order": "SHELF-A3",      <- shelf being picked
        "battery":       null             <- filled by Teensy team; null until wired up
    }

Order payload (what app.py api_order() sends):
    {
        "command":  "PICK",
        "shelf_id": "SHELF_A07",
        "order_id": "a3f9b2c1"
    }

Dashboard state names (must match ROBOT_STATES in app.py):
    IDLE -> NAVIGATING -> SCANNING QR -> DETECTING BOX -> ALIGNING -> LIFTING -> DELIVERING -> IDLE
"""

import json
import paho.mqtt.client as mqtt

TOPIC_STATUS = 'amr/status'   # we publish here — web app reads it
TOPIC_ORDERS = 'amr/orders'   # web app publishes here — we subscribe

# Map vision pipeline stage names -> dashboard display state names
STAGE_TO_STATE = {
    'RUNNING':  'NAVIGATING',
    'STAGE_1':  'SCANNING QR',
    'STAGE_2':  'DETECTING BOX',
    'STAGE_3':  'ALIGNING',
    'GRIPPING': 'LIFTING',
    'DONE':     'IDLE',
    'ERROR':    'IDLE',
}


class AMRMqttPublisher:
    """
    Publishes vision pipeline events to the Mosquitto broker so the web
    dashboard can display real-time robot state.

    Usage:
        mqtt = AMRMqttPublisher(broker_host="192.168.1.100",
                                shelf_id="SHELF-A3")
        mqtt.publish_stage("STAGE_1")
        mqtt.close()
    """

    def __init__(self,
                 broker_host: str = "localhost",
                 broker_port: int = 1883,
                 shelf_id: str    = "",
                 dry_run: bool    = False,
                 client_id: str   = "amr_vision"):

        self._dry_run      = dry_run
        self._shelf_id     = shelf_id     # included in every status publish
        self._battery      = None         # set externally when Teensy reports it
        self._client       = None
        self._connected    = False

        # Callback: called when web dashboard sends a pick order
        # Set to: callable(shelf_id: str, sku: str, order_id: str)
        self.on_pick_order = None
        self.on_stop       = None         # called on STOP command

        if dry_run:
            print("[MQTT] dry_run — messages printed, not sent")
            return

        # client_id must be UNIQUE per connection — a broker kicks off any
        # existing client that reconnects with the same id. vision_main.py uses
        # the default; mqtt_bridge passes its own so both can coexist if needed.
        self._client = mqtt.Client(client_id=client_id)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        # connect_async + loop_start: the network thread establishes the link and
        # AUTO-RECONNECTS if the broker restarts or isn't up yet (common on the
        # Jetson at boot). Messages published while offline are dropped by _pub
        # (self._connected guard), not crashed on.
        try:
            self._client.connect_async(broker_host, broker_port, keepalive=60)
            self._client.loop_start()
            print(f"[MQTT] Connecting to {broker_host}:{broker_port} (auto-reconnect) ...")
        except Exception as e:
            print(f"[MQTT] Cannot start MQTT client: {e} — falling back to dry_run")
            self._dry_run = True

    # ── Status publishing ──────────────────────────────────────────────────────

    def publish_stage(self, stage_name: str):
        """
        Publish a full status update to amr/status.
        Called every time the pipeline transitions stages.
        stage_name: "STAGE_1", "STAGE_2", "STAGE_3", "GRIPPING", "DONE", "ERROR"
        """
        web_state = STAGE_TO_STATE.get(stage_name, "IDLE")
        self._publish_status(web_state, stage_name)

    def publish_status(self, status: str):
        """Called at pipeline start ("RUNNING") and end ("DONE"/"ERROR:...")."""
        stage = status if status in STAGE_TO_STATE else "RUNNING"
        web_state = STAGE_TO_STATE.get(stage, "NAVIGATING")
        self._publish_status(web_state, stage)

    def publish_web_state(self, web_state: str, vision_stage: str = ""):
        """Publish an explicit dashboard state string, e.g. "IDLE", "NAVIGATING",
        "SCANNING QR", "DETECTING BOX", "ALIGNING", "LIFTING", "DELIVERING".

        Used by mqtt_bridge, which infers the state from ROS topics in the
        integrated mission rather than from vision pipeline stage names."""
        self._publish_status(web_state, vision_stage or web_state)

    def publish_shelf_confirmed(self, shelf_id: str):
        """Called when Stage 1 confirms the shelf QR. Updates current_order."""
        self._shelf_id = shelf_id
        self._publish_status("SCANNING QR", "STAGE_1")

    def publish_sku_confirmed(self, sku: str, distance_mm: int):
        """Called when Stage 2 confirms box QR + measures depth."""
        print(f"[MQTT] SKU confirmed: {sku}  dist={distance_mm}mm")
        self._publish_status("DETECTING BOX", "STAGE_2")

    def publish_servo(self, offset_px: int, correction: float, aligned: bool):
        """Called each servo cycle in Stage 3. No separate topic — status is enough."""
        pass   # dashboard shows ALIGNING state; servo detail not needed in dashboard

    def publish_grip(self):
        """Called when suction cup activates."""
        self._publish_status("LIFTING", "GRIPPING")

    def publish_error(self, reason: str):
        """Called on pipeline ERROR."""
        print(f"[MQTT] Error: {reason}")
        payload = json.dumps({
            "state":         "IDLE",
            "vision_stage":  f"ERROR:{reason}",
            "current_order": self._shelf_id,
            "battery":       self._battery,
        })
        self._pub(TOPIC_STATUS, payload)

    def set_battery(self, percent: float):
        """Called by whoever reads the battery sensor (Teensy team)."""
        self._battery = percent

    def set_current_order(self, shelf_id: str):
        """Set the shelf/order id echoed in every status payload's current_order."""
        self._shelf_id = shelf_id

    # ── Internal ───────────────────────────────────────────────────────────────

    def _publish_status(self, web_state: str, vision_stage: str):
        payload = json.dumps({
            "state":         web_state,
            "vision_stage":  vision_stage,
            "current_order": self._shelf_id,
            "battery":       self._battery,
        })
        self._pub(TOPIC_STATUS, payload)

    def _pub(self, topic: str, payload: str):
        if self._dry_run:
            print(f"[MQTT DRY-RUN] {topic}  >>  {payload}")
            return
        if not self._connected:
            print(f"[MQTT] Not connected — dropped: {topic}")
            return
        self._client.publish(topic, payload, qos=1, retain=False)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            client.subscribe(TOPIC_ORDERS, qos=1)
            print(f"[MQTT] Connected — subscribed to {TOPIC_ORDERS}")
        else:
            print(f"[MQTT] Connection failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            print(f"[MQTT] Disconnected (rc={rc}) — will reconnect")

    def _on_message(self, client, userdata, msg):
        """Handle incoming commands from the web dashboard."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            command = payload.get("command", "")

            if command == "PICK":
                shelf_id = payload.get("shelf_id", "")
                order_id = payload.get("order_id", "")
                # Web app sends shelf_id only — SKU comes from the order system
                # For now, the SKU is passed at startup via CLI --sku
                print(f"[MQTT] PICK order received: shelf={shelf_id} id={order_id}")
                if self.on_pick_order and shelf_id:
                    self.on_pick_order(shelf_id, order_id)

            elif command == "STOP":
                print("[MQTT] STOP command received from dashboard")
                if self.on_stop:
                    self.on_stop()

        except Exception as e:
            print(f"[MQTT] Bad message: {e}")

    def close(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            print("[MQTT] Disconnected cleanly.")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    print("MQTT publisher test — dry_run")

    with AMRMqttPublisher(shelf_id="SHELF-A3", dry_run=True) as m:
        m.publish_status("RUNNING")
        m.publish_stage("STAGE_1")
        time.sleep(0.1)
        m.publish_shelf_confirmed("SHELF-A3")
        m.publish_stage("STAGE_2")
        time.sleep(0.1)
        m.publish_sku_confirmed("BOX-SKU-001", 450)
        m.publish_stage("STAGE_3")
        time.sleep(0.1)
        m.publish_grip()
        time.sleep(0.1)
        m.publish_stage("DONE")
        print("\nAll messages above go to amr/status — web dashboard reads from there.")
