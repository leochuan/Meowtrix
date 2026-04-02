# 🐱 Cat Sentry Lite

Standalone cat escape monitor — single Python script with built-in Web UI.  
No Docker, no Frigate, no MQTT. Just RTSP + YOLO + push notifications.

## Features

- **Real-time MJPEG preview** in browser with polygon zone drawing
- **Motion-gated YOLO inference** — only wakes the model when pixels change, saving CPU
- **Polygon forbidden zone** — draw any shape on the live camera feed
- **Enter/leave state machine** — alerts on entry; must leave and re-enter to trigger again
- **Dual push** — Bark (iOS) + DingTalk (with base64 screenshot, no public URL needed)
- **Annotated snapshots** — bounding boxes, confidence labels, zone outline on full-frame captures
- **Auto hardware acceleration** — MPS (Apple Silicon) / CUDA / CPU
- **All config via Web UI** — RTSP URL, thresholds, zone, push URLs, all editable at runtime

## Quick Start

```bash
cp config.json.example config.json   # Edit with your RTSP URL + push keys
pip install -r requirements.txt
python cat_sentry_pro.py
# Open http://localhost:8080
```

## Web UI

1. The live camera feed streams automatically in the browser
2. Click to draw a polygon around the forbidden zone (at least 3 points)
3. Configure detection parameters on the right panel
4. Click **Save** then **Start**

## Configuration

All settings are stored in `config.json` and editable via the Web UI:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rtsp_url` | RTSP stream URL | — |
| `bark_urls` | Bark push URLs (array, one per account) | `[]` |
| `dingtalk_webhook` | DingTalk robot webhook URL | `""` |
| `zone_points` | Polygon vertices as normalized `[x, y]` pairs | `[]` |
| `yolo_model` | YOLO model file (`yolov8n.pt` / `yolov8s.pt` / `yolov8m.pt`) | `yolov8s.pt` |
| `yolo_conf` | Confidence threshold (lower = sensitive, higher = strict) | `0.45` |
| `motion_threshold` | Pixel change count to trigger YOLO | `5000` |
| `roi_padding_pct` | Expand detection area beyond zone (e.g. 0.2 = 20%) | `0.2` |
| `snapshot_dir` | Where to save alert screenshots | `snapshots` |
| `server_host` | LAN IP for Bark image URLs (optional) | `""` |
| `web_port` | Web UI port | `8080` |

## RTSP URL Examples

| Camera | URL Format |
|--------|-----------|
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/101` |
| Dahua | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` |
| TP-Link | `rtsp://user:pass@IP:554/stream1` |
| IP Webcam (Android) | `rtsp://IP:8080/h264_opus.sdp` |

## How Detection Works

```
RTSP frame → crop ROI region → motion detect (cv2.absdiff)
                                      ↓ motion detected
                                 YOLO inference (ROI only)
                                      ↓ cat found
                                 polygon collision test
                                      ↓ cat in zone
                                 alert + snapshot + push
```

- **No motion → YOLO doesn't run** (near-zero CPU)
- **YOLO runs only on the small ROI crop**, not the full frame
- **State machine**: alert fires once on entry, re-arms only after cat leaves
