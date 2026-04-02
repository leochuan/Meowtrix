# 🐱 Meowtrix — Cat Escape Monitor

Two independent solutions for monitoring your cat near the door:

1. **Docker Stack** (Frigate + MQTT + Bark) — full NVR pipeline
2. **Cat Sentry Pro** — lightweight single-script solution with Web UI

---

## Solution 1: Docker Stack

Push notifications to your iPhone when your cat approaches the door.

### Architecture

```
IP Webcam (RTSP) → Frigate (detection) → Mosquitto (MQTT) → monitor.py → Bark (push)
                                                                ↑
                                                     Zone Picker (web UI)
```

### Quick Start

```bash
# 1. Edit .env — fill in IPs, RTSP address, Bark device key
cp .env.example .env
vim .env

# 2. Start all services (Frigate + Mosquitto + Monitor + Zone Picker)
docker compose up -d
```

That's it. All services run inside Docker — no need to install Python or manage virtualenv locally.

### Configure the Door Zone

1. Open Zone Picker: `http://<your-ip>:8090`
2. Click on the camera feed to mark the corners of the door area
3. Click **Save & Apply** — the config is saved and Frigate restarts automatically

### Recording

Recordings are saved with the following retention policy:

| Type | Retention |
|------|-----------|
| Continuous (no events) | Not retained |
| Motion detected | 3 days |
| Alerts / Detections (cat) | 7 days |

---

## Solution 2: Cat Sentry Pro

A standalone Python script with built-in Web UI. No Docker, no Frigate, no MQTT — just RTSP + YOLO + push notifications.

### Features

- **Real-time MJPEG preview** in browser with polygon zone drawing
- **Motion-gated YOLO inference** — only wakes the model when pixels change, saving CPU
- **Polygon forbidden zone** — draw any shape, not just rectangles
- **Enter/leave state machine** — alerts only when cat enters; must leave and re-enter to trigger again
- **Dual push channels** — Bark (iOS) + DingTalk (with base64 screenshot, no public URL needed)
- **Annotated snapshots** — bounding boxes, confidence labels, and zone outline drawn on full-frame captures
- **Auto hardware acceleration** — MPS (Apple Silicon) / CUDA / CPU
- **All config via Web UI** — RTSP URL, thresholds, zone, push URLs, all editable at runtime
- **Compatible with all RTSP cameras** — Hikvision, Dahua, TP-Link, IP Webcam, etc.

### Quick Start

```bash
cd cat-sentry
cp config.json.example config.json   # Edit with your RTSP URL + push keys
pip install -r requirements.txt
python cat_sentry_pro.py
# Open http://localhost:8080
```

### Web UI

1. The live camera feed streams in the browser
2. Click to draw a polygon around the forbidden zone (at least 3 points)
3. Configure detection parameters on the right panel
4. Click **Save** then **Start**

### Configuration

All settings are stored in `config.json` and editable via the Web UI:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rtsp_url` | RTSP stream URL | — |
| `bark_urls` | Bark push URLs (array, one per account) | `[]` |
| `dingtalk_webhook` | DingTalk robot webhook URL | `""` |
| `zone_points` | Polygon vertices as normalized `[x, y]` pairs | `[]` |
| `yolo_model` | YOLO model file (n/s/m) | `yolov8s.pt` |
| `yolo_conf` | Confidence threshold (lower = more sensitive) | `0.45` |
| `motion_threshold` | Pixel change count to trigger YOLO | `5000` |
| `roi_padding_pct` | How much to expand detection area beyond zone | `0.2` |
| `snapshot_dir` | Where to save alert screenshots | `snapshots` |
| `server_host` | LAN IP for Bark image URLs (optional) | `""` |
| `web_port` | Web UI port | `8080` |

### RTSP URL Examples

| Camera | URL Format |
|--------|-----------|
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/101` |
| Dahua | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` |
| TP-Link | `rtsp://user:pass@IP:554/stream1` |
| IP Webcam (Android) | `rtsp://IP:8080/h264_opus.sdp` |

---

## Project Structure

```
├── .env                          # Docker stack config (IPs, ports, Bark key)
├── docker-compose.yml            # Docker services: Frigate + Mosquitto + Monitor + Zone Picker
├── Dockerfile                    # Monitor service image
├── Dockerfile.zone-picker        # Zone Picker service image
├── monitor.py                    # MQTT → Bark push logic
├── zone-picker-server.py         # Zone Picker backend
├── zone-picker.html              # Zone Picker frontend
├── config/
│   ├── frigate/config.yml        # Frigate detection, zone & recording config
│   └── mosquitto/mosquitto.conf  # MQTT broker config
├── cat-sentry/                   # Standalone Cat Sentry Pro
│   ├── cat_sentry_pro.py         # Main script (server + detection engine)
│   ├── index.html                # Web UI (Chinese)
│   ├── config.json.example       # Config template
│   └── requirements.txt          # Python dependencies
└── storage/                      # Persistent data (auto-generated)
```
