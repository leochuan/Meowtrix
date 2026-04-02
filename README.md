# 🐱 Meowtrix — Cat Escape Monitor

Keep your cat from sneaking out the door. Two solutions, pick what fits your setup.

## Solutions

| | [**Lite**](lite/) | [**Frigate**](frigate/) |
|---|---|---|
| **Architecture** | Single Python script | Docker stack (Frigate + MQTT) |
| **Detection** | YOLOv8 (direct) | Frigate NVR built-in |
| **Setup** | `pip install` + run | `docker compose up` |
| **Web UI** | Built-in (live stream + zone drawing + config) | Frigate UI + Zone Picker |
| **Push channels** | Bark (iOS, with annotated screenshot) | Bark |
| **Recording** | Alert snapshots only | Continuous + event recording |
| **Best for** | Quick setup, single camera, low-power devices | Multi-camera, NVR, long-term recording |
| **Dependencies** | Python + OpenCV + Ultralytics | Docker |

## Quick Comparison

**Lite** — Zero infrastructure. One script, one camera, instant alerts with annotated screenshots. Start monitoring in 2 minutes.

**Frigate** — Full NVR pipeline. Continuous recording, event timeline, multi-camera support. Needs Docker and more resources.

## Project Structure

```
├── README.md                 # This file
├── lite/                     # Standalone Python solution
│   ├── cat_sentry_pro.py     # Server + detection engine
│   ├── index.html            # Web UI (Chinese)
│   ├── config.json.example   # Config template
│   ├── requirements.txt      # Python dependencies
│   ├── build_exe.bat         # Windows exe build script
│   ├── build.spec            # PyInstaller spec
│   └── README.md
├── frigate/                  # Docker-based Frigate solution
│   ├── docker-compose.yml    # All services
│   ├── Dockerfile            # Monitor image
│   ├── Dockerfile.zone-picker
│   ├── monitor.py            # MQTT → Bark push
│   ├── zone-picker-server.py
│   ├── zone-picker.html
│   ├── .env.example          # Config template
│   ├── requirements.txt
│   ├── config/               # Frigate + Mosquitto configs
│   ├── storage/              # Runtime data (gitignored)
│   └── README.md
```
