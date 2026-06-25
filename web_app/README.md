# Navixa Web Dashboard

Operator control panel + brand landing page for the Navixa AMR warehouse robot.

## Quick Start

### 1. Install dependencies
```bash
pip install flask paho-mqtt
```

### 2. Start the MQTT broker (if not already running)
```bash
# Windows
mosquitto -v

# Jetson / Linux
sudo systemctl start mosquitto
```

### 3. Run the server
```bash
# Development (Windows)
python app.py

# Production (Jetson — accessible from other devices on the network)
HOST=0.0.0.0 PORT=5000 python app.py
```

### 4. Open in browser
```
http://localhost:5000          → Landing page
http://localhost:5000/dashboard → Operator dashboard
```

Default password: **navixa2026**

---

## Environment Variables

| Variable            | Default       | Description                              |
|---------------------|---------------|------------------------------------------|
| `DASHBOARD_PASSWORD`| navixa2026    | Login password for operator dashboard    |
| `MQTT_BROKER`       | localhost     | Mosquitto broker hostname or IP          |
| `MQTT_PORT`         | 1883          | MQTT broker port                         |
| `SECRET_KEY`        | (random)      | Flask session signing key                |
| `HOST`              | 0.0.0.0       | Flask bind address                       |
| `PORT`              | 5000          | Flask port                               |
| `DEBUG`             | false         | Flask debug mode (never true in prod)    |

---

## MQTT Contract

**Robot → Web** (`amr/status`):
```json
{
  "state": "NAVIGATING",
  "vision_stage": "SCANNING QR",
  "current_order": "SHELF_A07",
  "battery": 78.5
}
```

**Web → Robot** (`amr/orders`):
```json
{ "command": "PICK", "shelf_id": "SHELF_A07", "order_id": "a3f9b2c1" }
{ "command": "STOP" }
```

---

## File Structure

```
06_web_dashboard/
├── app.py                  Flask backend — routes, MQTT, in-memory store
├── templates/
│   ├── index.html          Landing page
│   ├── login.html          Login page
│   └── dashboard.html      Operator dashboard
├── static/
│   ├── style.css           Complete design system
│   └── script.js           Frontend polling + order submission
└── README.md
```

---

## Security Notes (for hospital deployment, these must be addressed)

- **HTTP only** — credentials are in plaintext on the local network. Add HTTPS via nginx + Let's Encrypt before any real deployment.
- **MQTT no auth** — the mosquitto broker has no authentication. Anyone on the same subnet can command the robot. Add TLS + password authentication to `mosquitto.conf`.
- **No CSRF protection** — acceptable for a closed lab network; add Flask-WTF for production.
- **In-memory storage** — order history is lost on server restart. Add SQLite via Flask-SQLAlchemy for persistent storage.

---

## Running as a systemd service (Jetson)

Create `/etc/systemd/system/navixa-web.service`:
```ini
[Unit]
Description=Navixa Web Dashboard
After=network.target mosquitto.service

[Service]
User=robot
WorkingDirectory=/home/robot/06_web_dashboard
Environment=DASHBOARD_PASSWORD=navixa2026
Environment=HOST=0.0.0.0
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable navixa-web
sudo systemctl start navixa-web
```
