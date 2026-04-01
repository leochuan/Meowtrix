# 🐱 Cat Escape Monitor

Push notifications to your iPhone when your cat approaches the door.

## Architecture

```
IP Webcam (RTSP) → Frigate (detection) → Mosquitto (MQTT) → monitor.py → Bark (push)
                                                                ↑
                                                     Zone Picker (web UI)
```

## Quick Start

```bash
# 1. Edit .env — fill in IPs, RTSP address, Bark device key
cp .env.example .env
vim .env

# 2. Start all services (Frigate + Mosquitto + Monitor + Zone Picker)
docker compose up -d
```

That's it. All services run inside Docker — no need to install Python or manage virtualenv locally.

## Configure the Door Zone

1. Open Zone Picker: `http://<your-ip>:8090`
2. Click on the camera feed to mark the corners of the door area
3. Click **Save & Apply** — the config is saved and Frigate restarts automatically

## Recording

Recordings are saved with the following retention policy:

| Type | Retention |
|------|-----------|
| Continuous (no events) | Not retained |
| Motion detected | 3 days |
| Alerts / Detections (cat) | 7 days |

## Project Structure

```
├── .env                          # 🔧 Unified config (IPs, ports, Bark key)
├── docker-compose.yml            # All services: Frigate + Mosquitto + Monitor + Zone Picker
├── Dockerfile                    # Monitor service image
├── Dockerfile.zone-picker        # Zone Picker service image
├── monitor.py                    # Core logic (MQTT → Bark push)
├── zone-picker-server.py         # Zone Picker backend (save zone → restart Frigate)
├── zone-picker.html              # Zone Picker frontend
├── requirements.txt              # Python dependencies (installed in Docker)
├── config/
│   ├── frigate/config.yml        # Frigate detection, zone & recording config
│   └── mosquitto/mosquitto.conf  # MQTT broker config
└── storage/                      # Persistent data (auto-generated)
```

## Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `MINI_IP` | Host machine LAN IP | `192.168.1.100` |
| `RTSP_URL` | IP Webcam RTSP address | — |
| `FRIGATE_PORT` | Frigate Web UI port | `5001` |
| `ZONE_PICKER_PORT` | Zone Picker port | `8090` |
| `BARK_SERVER` | Bark server URL | `https://api.day.app` |
| `BARK_DEVICE_KEY` | Bark device token | — |
| `EVENT_COOLDOWN` | Push cooldown per event (sec) | `30` |

## Platform Migration

Currently using CPU detection. To migrate, update `detectors` in `config/frigate/config.yml`:

| Platform | Detector |
|----------|----------|
| Raspberry Pi + Coral USB | `type: edgetpu, device: usb` |
| x86 + OpenVINO | `type: openvino, device: AUTO` |
| NVIDIA GPU | `type: tensorrt` |
