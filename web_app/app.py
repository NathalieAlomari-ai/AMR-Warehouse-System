"""
Navixa AMR Web Control System — Flask Backend
----------------------------------------------
Runs on Jetson Orin Nano (prod) or Windows (dev).
Bridges the browser operator interface with the robot via MQTT.

Environment variables (all optional — defaults work for local dev):
  SECRET_KEY         Flask session signing key (auto-random if unset)
  DASHBOARD_PASSWORD Login password (default: navixa2026)
  MQTT_BROKER        Broker hostname/IP (default: localhost)
  MQTT_PORT          Broker port (default: 1883)
  HOST               Flask bind address (default: 0.0.0.0)
  PORT               Flask port (default: 5000)
  DEBUG              Set to 'true' for Flask debug mode

Jetson vs Windows:
  - No code changes needed; paho-mqtt API is identical on both platforms.
  - On Jetson, set HOST=0.0.0.0 so other devices on the lab network can reach the dashboard.
  - On Windows dev, the default 0.0.0.0 also works fine.
"""

import os
import json
import uuid
import threading
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify
)
import paho.mqtt.client as mqtt

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

# Secret key signs the session cookie. urandom(24) generates a fresh random key
# on every restart, which means sessions are invalidated on restart.
# For persistent sessions across restarts: export SECRET_KEY=<fixed-string>
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# ── Configuration ─────────────────────────────────────────────────────────────

DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'navixa2026')
MQTT_BROKER        = os.environ.get('MQTT_BROKER', 'localhost')
MQTT_PORT          = int(os.environ.get('MQTT_PORT', 1883))
TOPIC_STATUS       = 'amr/status'   # robot publishes here
TOPIC_ORDERS       = 'amr/orders'   # robot subscribes here

# Robot state machine — ordered for the pipeline progress indicator
ROBOT_STATES = [
    'IDLE',
    'NAVIGATING',
    'SCANNING QR',
    'DETECTING BOX',
    'ALIGNING',
    'LIFTING',
    'DELIVERING',
]

# ── In-memory store ───────────────────────────────────────────────────────────
# Both Flask request threads AND the paho background thread read/write these.
# Always acquire orders_lock before touching 'orders' or 'robot_status'.

orders_lock = threading.Lock()

orders: list = []   # list of order dicts (see structure below)
"""
Each order:
{
  "id":           str   — 8-char hex UUID
  "shelf_id":     str   — e.g. "SHELF_A07"
  "status":       str   — "PENDING" | "IN_PROGRESS" | "COMPLETED" | "FAILED"
  "created_at":   str   — ISO 8601 UTC
  "completed_at": str | None
}
"""

robot_status: dict = {
    'state':         'IDLE',
    'vision_stage':  None,
    'current_order': None,
    'battery':       None,
    'last_seen':     None,   # ISO 8601 UTC of last MQTT message
    'connected':     False,
}

# ── MQTT contract ─────────────────────────────────────────────────────────────
# amr/status (robot → web):
#   {"state": "NAVIGATING", "vision_stage": null,
#    "current_order": "SHELF_A07", "battery": 78.5}
#
# amr/orders (web → robot):
#   {"command": "PICK", "shelf_id": "SHELF_A07", "order_id": "a3f9b2c1"}
#   {"command": "STOP"}

# ── MQTT callbacks ────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(TOPIC_STATUS, qos=1)
        print(f'[MQTT] Connected — subscribed to {TOPIC_STATUS}')
    else:
        print(f'[MQTT] Connection failed, rc={rc}')


def on_message(client, userdata, msg):
    # This runs in paho's background thread — must use the lock.
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        now = datetime.now(timezone.utc).isoformat()

        with orders_lock:
            # Update robot status from incoming telemetry
            robot_status['state']         = payload.get('state', robot_status['state'])
            robot_status['vision_stage']  = payload.get('vision_stage')
            robot_status['current_order'] = payload.get('current_order')
            robot_status['battery']       = payload.get('battery')
            robot_status['last_seen']     = now
            robot_status['connected']     = True

            incoming_state   = payload.get('state', '')
            incoming_order   = payload.get('current_order')

            # Transition matching PENDING order → IN_PROGRESS when robot picks it up
            if incoming_order and incoming_state != 'IDLE':
                for order in orders:
                    if order['shelf_id'] == incoming_order and order['status'] == 'PENDING':
                        order['status'] = 'IN_PROGRESS'
                        break

            # Transition IN_PROGRESS order → COMPLETED when robot returns to IDLE
            if incoming_state == 'IDLE':
                for order in orders:
                    if order['status'] == 'IN_PROGRESS':
                        order['status']       = 'COMPLETED'
                        order['completed_at'] = now
                        break

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        # Never let a bad message crash the callback — paho swallows exceptions
        # silently, so log here to make issues visible.
        print(f'[MQTT] Bad message ignored: {exc}')


def on_disconnect(client, userdata, rc):
    with orders_lock:
        robot_status['connected'] = False
    print(f'[MQTT] Disconnected, rc={rc}')


# ── MQTT client ───────────────────────────────────────────────────────────────

mqtt_client = mqtt.Client(client_id='navixa-web', protocol=mqtt.MQTTv311)
mqtt_client.on_connect    = on_connect
mqtt_client.on_message    = on_message
mqtt_client.on_disconnect = on_disconnect

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()   # background thread — does not block Flask
    print(f'[MQTT] Background loop started — broker={MQTT_BROKER}:{MQTT_PORT}')
except Exception as exc:
    # Don't crash on startup if the broker isn't running yet (common on Windows dev).
    # The dashboard will show "Robot Offline" until the broker becomes available.
    print(f'[MQTT] Could not connect: {exc} — dashboard will show offline status')

# ── Auth helper ───────────────────────────────────────────────────────────────

def login_required(f):
    """Decorator: redirect to /login if the session has no authenticated flag."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_connected() -> bool:
    """True if we received an MQTT message within the last 10 seconds."""
    last = robot_status.get('last_seen')
    if not last:
        return False
    try:
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        return delta.total_seconds() < 10
    except Exception:
        return False


def _has_active_order() -> bool:
    """True if any order is currently IN_PROGRESS. Caller must hold lock."""
    return any(o['status'] == 'IN_PROGRESS' for o in orders)


def _has_pending_order() -> bool:
    """True if any order is PENDING or IN_PROGRESS. Caller must hold lock."""
    return any(o['status'] in ('PENDING', 'IN_PROGRESS') for o in orders)

# ── Page routes ───────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == DASHBOARD_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('dashboard'))
        error = 'Incorrect password.'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', robot_states=ROBOT_STATES)

# ── API routes ────────────────────────────────────────────────────────────────

@app.route('/api/order', methods=['POST'])
@login_required
def api_order():
    data     = request.get_json(silent=True) or {}
    shelf_id = data.get('shelf_id', '').strip().upper()

    if not shelf_id:
        return jsonify({'success': False, 'error': 'shelf_id is required'}), 400

    with orders_lock:
        if _has_pending_order():
            return jsonify({
                'success': False,
                'error': 'An order is already active. Wait for it to complete.'
            }), 409

        order_id = uuid.uuid4().hex[:8]
        order = {
            'id':           order_id,
            'shelf_id':     shelf_id,
            'status':       'PENDING',
            'created_at':   datetime.now(timezone.utc).isoformat(),
            'completed_at': None,
        }
        orders.append(order)

    # Publish outside the lock — MQTT publish is thread-safe internally
    payload = json.dumps({
        'command':  'PICK',
        'shelf_id': shelf_id,
        'order_id': order_id,
    })
    mqtt_client.publish(TOPIC_ORDERS, payload, qos=1)
    print(f'[ORDER] Published PICK — shelf={shelf_id}, id={order_id}')

    return jsonify({'success': True, 'order_id': order_id, 'shelf_id': shelf_id})


@app.route('/api/status')
@login_required
def api_status():
    with orders_lock:
        connected    = _is_connected()
        status_snap  = dict(robot_status)
        status_snap['connected'] = connected

        active  = [o for o in orders if o['status'] in ('PENDING', 'IN_PROGRESS')]
        history = [o for o in orders if o['status'] in ('COMPLETED', 'FAILED')]

    return jsonify({
        'robot':   status_snap,
        'orders':  active,
        'history': list(reversed(history[-50:])),  # newest first, last 50
        'states':  ROBOT_STATES,
    })


@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    # QoS 2 = exactly-once delivery — critical for safety commands
    payload = json.dumps({'command': 'STOP'})
    mqtt_client.publish(TOPIC_ORDERS, payload, qos=2)
    print('[STOP] Emergency stop published')

    # Mark any running order as FAILED immediately on the web side.
    # The robot will confirm via amr/status once it halts.
    now = datetime.now(timezone.utc).isoformat()
    with orders_lock:
        for order in orders:
            if order['status'] in ('PENDING', 'IN_PROGRESS'):
                order['status']       = 'FAILED'
                order['completed_at'] = now

    return jsonify({'success': True, 'message': 'STOP command sent'})

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    host  = os.environ.get('HOST', '0.0.0.0')
    port  = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'

    print(f'[Navixa] Dashboard → http://{host}:{port}')
    print(f'[Navixa] Password  → {DASHBOARD_PASSWORD}')

    # threaded=True is required: paho callback thread + multiple browser poll threads
    # must all access the app concurrently without deadlocking.
    app.run(host=host, port=port, debug=debug, threaded=True)
