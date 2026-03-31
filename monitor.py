#!/usr/bin/env python3
"""
============================================================
Cat Escape Monitor - Core Logic
============================================================
Pipeline:
  1. Subscribe to Frigate MQTT events (frigate/events)
  2. Filter: label == 'cat' and entered door_zone
  3. Secondary inference: call recognize_individual_cat() (placeholder)
  4. Push: send snapshot notification via Bark

Dependencies: pip install -r requirements.txt
Usage: python monitor.py (all config read from .env)
============================================================
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import requests

# Load .env shared with docker-compose
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# ============================================================
# Configuration (all from .env, defaults are fallbacks only)
# ============================================================

MINI_IP = os.getenv("MINI_IP", "192.168.1.100")
FRIGATE_PORT = os.getenv("FRIGATE_PORT", "5001")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
BARK_SERVER = os.getenv("BARK_SERVER", "https://api.day.app")
BARK_DEVICE_KEY = os.getenv("BARK_DEVICE_KEY", "your_bark_device_key_here")
TARGET_ZONE = os.getenv("TARGET_ZONE", "door_zone")
EVENT_COOLDOWN = int(os.getenv("EVENT_COOLDOWN", "30"))

FRIGATE_BASE_URL = f"http://{MINI_IP}:{FRIGATE_PORT}"

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cat-monitor")

# ============================================================
# Event deduplication
# ============================================================

_event_cache: dict[str, float] = {}


def is_duplicate_event(event_id: str) -> bool:
    """Only trigger once per event_id within the cooldown window."""
    now = time.time()
    if event_id in _event_cache:
        if now - _event_cache[event_id] < EVENT_COOLDOWN:
            return True
    _event_cache[event_id] = now

    # Purge entries older than 5 minutes
    expired = [k for k, v in _event_cache.items() if now - v > 300]
    for k in expired:
        del _event_cache[k]
    return False


# ============================================================
# Secondary inference (placeholder)
# ============================================================

def recognize_individual_cat(image_url: str) -> Optional[str]:
    """
    Identify individual cat. Returns None in fallback mode.

    To integrate a custom YOLO model:
      1. Train a YOLOv8-cls model (50-100 images per cat)
      2. Replace this function:
         from ultralytics import YOLO
         CAT_MODEL = YOLO("path/to/cat_classifier.pt")
         def recognize_individual_cat(image_url):
             results = CAT_MODEL.predict(image_url)
             if results and results[0].probs:
                 if results[0].probs.top1conf > 0.8:
                     return results[0].names[results[0].probs.top1]
             return None
      3. Uncomment ultralytics/torch in requirements.txt
    """
    logger.debug(f"Secondary inference placeholder, image_url={image_url}")
    return None


# ============================================================
# Bark push notification
# ============================================================

def send_bark_notification(
    title: str,
    body: str,
    image_url: Optional[str] = None,
    group: str = "Cat Monitor",
) -> bool:
    """Send iOS push notification via Bark."""
    url = f"{BARK_SERVER}/{BARK_DEVICE_KEY}"

    payload = {
        "title": title,
        "body": body,
        "group": group,
        "sound": "alarm",
        "level": "timeSensitive",
        "isArchive": 1,
    }

    if image_url:
        payload["icon"] = image_url
        payload["image"] = image_url
        payload["url"] = FRIGATE_BASE_URL

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 200:
            logger.info(f"✅ Bark push sent: {title}")
            return True
        logger.warning(f"⚠️ Bark unexpected response: {result}")
        return False
    except requests.exceptions.ConnectionError:
        logger.error(f"❌ Bark connection failed: {BARK_SERVER}")
        return False
    except requests.exceptions.Timeout:
        logger.error("❌ Bark request timed out")
        return False
    except Exception as e:
        logger.error(f"❌ Bark push error: {e}")
        return False


# ============================================================
# Frigate event handler
# ============================================================

def handle_frigate_event(payload: dict) -> None:
    """Process a Frigate MQTT event."""
    event_type = payload.get("type")
    after = payload.get("after", {})

    event_id = after.get("id", "unknown")
    label = after.get("label", "")
    top_score = after.get("top_score") or 0
    has_snapshot = after.get("has_snapshot", False)
    camera = after.get("camera", "unknown")

    # Merge current_zones and entered_zones to avoid missed detections
    zones = set(after.get("current_zones", []) + after.get("entered_zones", []))

    # --- Filters ---
    if event_type not in ("new", "update"):
        return
    if label != "cat":
        return
    if TARGET_ZONE not in zones:
        return
    if is_duplicate_event(event_id):
        logger.debug(f"🔄 Event {event_id} in cooldown, skipping")
        return

    logger.info(
        f"🐱 Cat detected in {TARGET_ZONE}! "
        f"[camera={camera}, score={top_score:.2f}, event={event_id}]"
    )

    # --- Snapshot URL ---
    snapshot_url = (
        f"{FRIGATE_BASE_URL}/api/events/{event_id}/snapshot.jpg"
        if has_snapshot else None
    )
    if snapshot_url:
        logger.info(f"📸 Snapshot: {snapshot_url}")

    # --- Secondary inference ---
    cat_name = recognize_individual_cat(snapshot_url) if snapshot_url else None

    if cat_name:
        logger.info(f"🏷️ Identified: {cat_name}")
        title = f"⚠️ {cat_name} is escaping!"
        body = f"{cat_name} detected in {TARGET_ZONE} on {camera} (confidence {top_score:.0%})"
    else:
        title = "⚠️ Cat escape alert!"
        body = f"Cat detected in {TARGET_ZONE} on {camera} (confidence {top_score:.0%})"

    send_bark_notification(title=title, body=body, image_url=snapshot_url)


# ============================================================
# MQTT callbacks
# ============================================================

def on_connect(client: mqtt.Client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info(f"✅ Connected to MQTT: {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe("frigate/events")
        logger.info("📡 Subscribed: frigate/events")
    else:
        logger.error(f"❌ MQTT connection failed, rc={rc}")


def on_disconnect(client: mqtt.Client, userdata, rc, properties=None, reasonCode=None):
    if rc != 0:
        logger.warning(f"⚠️ MQTT disconnected unexpectedly (rc={rc}), reconnecting...")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        handle_frigate_event(payload)
    except json.JSONDecodeError:
        logger.error(f"❌ JSON parse error: {msg.payload[:200]}")
    except Exception as e:
        logger.error(f"❌ Event handler error: {e}", exc_info=True)


# ============================================================
# Main
# ============================================================

def main():
    logger.info("=" * 50)
    logger.info("  🐱 Cat Escape Monitor")
    logger.info("=" * 50)
    logger.info(f"  MQTT     : {MQTT_HOST}:{MQTT_PORT}")
    logger.info(f"  Frigate  : {FRIGATE_BASE_URL}")
    logger.info(f"  Bark     : {BARK_SERVER}")
    logger.info(f"  Zone     : {TARGET_ZONE}")
    logger.info(f"  Cooldown : {EVENT_COOLDOWN}s")
    logger.info("=" * 50)

    if BARK_DEVICE_KEY == "your_bark_device_key_here":
        logger.warning("⚠️ Set BARK_DEVICE_KEY in .env!")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="cat-monitor",
        protocol=mqtt.MQTTv311,
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    try:
        logger.info(f"🔌 Connecting to MQTT: {MQTT_HOST}:{MQTT_PORT} ...")
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except ConnectionRefusedError:
        logger.error(
            f"❌ Cannot connect to MQTT ({MQTT_HOST}:{MQTT_PORT})\n"
            f"   Make sure: docker compose up -d"
        )
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ MQTT connection error: {e}")
        sys.exit(1)

    try:
        logger.info("👀 Listening for events...")
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down...")
        client.disconnect()
        sys.exit(0)


if __name__ == "__main__":
    main()
