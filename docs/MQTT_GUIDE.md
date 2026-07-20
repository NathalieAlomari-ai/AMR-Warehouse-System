# MQTT Guide — Navixa AMR (beginner friendly)

How the robot talks to the web dashboard, how to start it, and how to test every
piece step by step. No prior MQTT knowledge needed.

---

## 1. What is MQTT? (60 seconds)

MQTT is a **messaging post office**.

| MQTT word | Plain meaning |
|---|---|
| **Broker** | The post office. Software (`mosquitto`) that receives and forwards messages. |
| **Topic** | A labelled mailbox, e.g. `amr/status`. Just a text name. |
| **Publish** | Drop a letter into a mailbox. |
| **Subscribe** | Ask the post office: "send me a copy of everything in this mailbox." |

Key idea: **programs never talk to each other directly.** The robot publishes to the
broker; the dashboard subscribes to the broker. Neither knows the other exists.
If the broker is down, nothing works — always check it first.

---

## 2. Our system: who says what

We use exactly **two mailboxes (topics)**:

| Topic | Direction | Who publishes | Who subscribes |
|---|---|---|---|
| `amr/status` | robot → dashboard | `mqtt_bridge` (Jetson) | dashboard `app.py` (laptop) |
| `amr/orders` | dashboard → robot | dashboard `app.py` | `mqtt_bridge` |

```
   JETSON (robot)                          LAPTOP
 ┌────────────────┐                    ┌──────────────┐
 │  mqtt_bridge   │──amr/status──┐  ┌──│ dashboard    │
 │ (ROS ↔ MQTT)   │◀─amr/orders──┼──┼─▶│  app.py      │
 └────────────────┘              │  │  └──────────────┘
         ▲                    ┌──▼──┴──┐
   ROS topics                 │ MOSQUITTO│  ← the broker (runs on the Jetson)
 /vision/request              │  :1883   │
 /aux/command  etc.           └──────────┘
```

**What each message looks like**

`amr/status` (robot → dashboard), sent **every 3 seconds**:
```json
{"state": "IDLE", "vision_stage": "IDLE", "current_order": "", "battery": null}
```
`state` must be one of: `IDLE`, `NAVIGATING`, `SCANNING QR`, `DETECTING BOX`,
`ALIGNING`, `LIFTING`, `DELIVERING`.

`amr/orders` (dashboard → robot), sent when you press **PICK**:
```json
{"command": "PICK", "shelf_id": "SHELF-A3", "order_id": "a3f9b2c1"}
```

> The dashboard marks the robot **Offline** if no `amr/status` arrives for 10 seconds.
> That's why the bridge heartbeats every 3 s.

---

## 3. One-time setup on the Jetson (do once, ever)

```bash
sudo apt update && sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

By default mosquitto only accepts connections from the Jetson itself. To let the
laptop connect, add this config **once**:

```bash
sudo tee /etc/mosquitto/conf.d/amr.conf >/dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF
sudo systemctl restart mosquitto
```

Then find the Jetson's IP (**you need this for the laptop**):
```bash
hostname -I
```
Use the **first** address (e.g. `172.17.106.92`). Ignore `172.17.0.1` — that's Docker, not real.

> ⚠️ The IP can change when you join a different Wi-Fi. Re-check it each session.

---

## 4. Start everything (in this order)

**Jetson — terminal 1: broker**
```bash
sudo systemctl start mosquitto
systemctl is-active mosquitto          # must print: active
hostname -I                            # note the IP
```

**Jetson — terminal 2: the bridge**
```bash
cd ~/AMR-Warehouse-System/ros2_ws
source install/setup.bash
ros2 run amr_vision mqtt_bridge
```
Healthy output:
```
mqtt_bridge up — broker localhost:1883
[MQTT] Connected — subscribed to amr/orders
```

**Laptop — the dashboard** (Windows PowerShell):
```powershell
cd C:\Users\abdal\AMR-Warehouse-System\web_app
$env:MQTT_BROKER = "172.17.106.92"     # ← the Jetson IP from above
python app.py
```
Healthy output:
```
[MQTT] Background loop started — broker=172.17.106.92:1883
[MQTT] Connected — subscribed to amr/status
```
Open <http://localhost:5000> → should show **Robot Online**.

> On Linux/Mac the laptop command is: `MQTT_BROKER=172.17.106.92 python3 app.py`
> (PowerShell can't use that inline style — set `$env:` on its own line.)

---

## 5. Test it step by step

Each test proves **one link** in the chain. Run them in order; stop at the first failure.

### Test 1 — Is the broker alive? (on the Jetson)
```bash
mosquitto_sub -h localhost -t 'amr/#' -v
```
`amr/#` means "every topic starting with amr/". Leave this running — it's your
window into all traffic.

✅ **Pass:** it sits there without an error (and shows `amr/status` every 3 s if the bridge runs).
❌ **Fail:** "Connection refused" → broker not running → `sudo systemctl start mosquitto`.

### Test 2 — Can the laptop reach the broker? (on the laptop)
```powershell
python -c "import socket; s=socket.socket(); s.settimeout(3); print('reachable' if s.connect_ex(('172.17.106.92',1883))==0 else 'BLOCKED')"
```
✅ `reachable` → network path is fine.
❌ `BLOCKED` → see Troubleshooting T3.

### Test 3 — Is the bridge publishing? (Jetson, with bridge running)
Watch the Test 1 window. Every 3 seconds you should see:
```
amr/status {"state": "IDLE", "vision_stage": "IDLE", "current_order": "", "battery": null}
```
✅ **Pass:** heartbeat appears → robot → broker works.
❌ **Fail:** bridge prints `[MQTT] Not connected — dropped: amr/status` → broker is down.

### Test 4 — Does the dashboard receive? (fake a robot, no ROS needed)
From **any** machine:
```bash
mosquitto_pub -h 172.17.106.92 -t 'amr/status' -m '{"state":"ALIGNING","vision_stage":"X","current_order":"SHELF-A3","battery":null}'
```
✅ **Pass:** the dashboard flips to **ALIGNING** → broker → dashboard works.
❌ **Fail:** dashboard didn't change → it's connected to the wrong broker (check its
`broker=` startup line) or wasn't restarted after setting `MQTT_BROKER`.

### Test 5 — Does the dashboard reach the robot? (the PICK button)
Keep the Test 1 window open, then press **PICK** on the dashboard. You should see:
```
amr/orders {"command": "PICK", "shelf_id": "SHELF-A3", "order_id": "..."}
```
and the **bridge terminal** prints:
```
dashboard PICK shelf=SHELF-A3 → /mission/start
```
Confirm ROS actually got it (Jetson, another terminal):
```bash
ros2 topic echo /mission/start
```
✅ **Pass:** full loop works — the dashboard can start a mission.

You can also fake the order without the dashboard:
```bash
mosquitto_pub -h 172.17.106.92 -t 'amr/orders' -m '{"command":"PICK","shelf_id":"SHELF-A3","order_id":"t1"}'
```

---

## 6. Running for real

Once tests 1–5 pass, nothing extra is needed for MQTT. Start the bridge alongside
the rest of the stack and the dashboard mirrors the mission automatically:

- `/mission/start` fires → bridge reports `NAVIGATING`
- `/vision/request SHELF_QR` → `SCANNING QR`
- `/aux/command LIFT …` → `LIFTING`
- `/vision/request BOX_QR` → `ALIGNING`
- `PUMP ON` → carrying → `DELIVERING`
- robot stops moving → back to `IDLE`

> The bridge **infers** these from ROS topics, so labels are approximate (the drive
> home may briefly read `LIFTING`). Good enough for a live dashboard.

---

## 7. Troubleshooting

| # | Symptom | Cause & fix |
|---|---|---|
| T1 | Dashboard stuck on **Offline** | Bridge not running, or no `amr/status` for 10 s. Run Test 3. |
| T2 | Bridge prints `Not connected — dropped` | Broker down → `sudo systemctl start mosquitto`. |
| T3 | Test 2 says **BLOCKED** | (a) missing `listener 1883 0.0.0.0` config (§3); (b) firewall → `sudo ufw allow 1883`; (c) **university/corporate Wi-Fi blocks device-to-device** → use a phone hotspot or your own router, then re-check `hostname -I`. |
| T4 | Dashboard says `broker=localhost` at startup | `MQTT_BROKER` wasn't set. In PowerShell set `$env:MQTT_BROKER` on its **own line** before `python app.py`. |
| T5 | Wrong/old IP | The Jetson IP changes between networks. Re-run `hostname -I` and restart the dashboard. |
| T6 | PICK does nothing | Bridge not subscribed (check `[MQTT] Connected — subscribed to amr/orders`) or coordinator isn't running to act on `/mission/start`. |
| T7 | Nothing works after a reboot | mosquitto may not be enabled → `sudo systemctl enable --now mosquitto`. |
| T8 | Two dashboards / bridges fighting | Each MQTT client needs a **unique client id**. Don't run two copies of the same program against one broker. |

**Golden debugging rule:** keep `mosquitto_sub -h <jetson-ip> -t 'amr/#' -v` open in a
spare terminal the whole time. If a message shows up there, the publisher works — the
problem is on the receiving side. If it doesn't, the problem is the publisher.

---

## 8. Command cheat sheet

```bash
# --- broker (Jetson) ---
sudo systemctl start mosquitto            # start
systemctl is-active mosquitto             # is it running?
hostname -I                               # Jetson IP (first address)

# --- watch all traffic (best debug tool) ---
mosquitto_sub -h <jetson-ip> -t 'amr/#' -v

# --- fake a robot status (tests the dashboard) ---
mosquitto_pub -h <jetson-ip> -t 'amr/status' \
  -m '{"state":"ALIGNING","vision_stage":"X","current_order":"SHELF-A3","battery":null}'

# --- fake an order (tests the robot side) ---
mosquitto_pub -h <jetson-ip> -t 'amr/orders' \
  -m '{"command":"PICK","shelf_id":"SHELF-A3","order_id":"t1"}'

# --- the bridge (Jetson) ---
ros2 run amr_vision mqtt_bridge

# --- the dashboard (laptop, PowerShell) ---
$env:MQTT_BROKER = "<jetson-ip>"
python app.py
```

**Note:** `MQTT_ENABLED=0` is **only** for the Vercel cloud deployment (no broker there).
Never set it on the laptop/robot — MQTT is enabled by default.
