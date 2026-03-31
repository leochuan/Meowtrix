# 🐱 Cat Escape Monitor

Push notifications to your iPhone when your cat approaches the door.

## Architecture

```
IP Webcam (RTSP) → Frigate (detection) → Mosquitto (MQTT) → monitor.py → Bark (push)
```

## Quick Start

```bash
# 1. Edit .env — fill in IPs, RTSP address, Bark device key
vim .env

# 2. Start Docker services
docker compose up -d

# 3. Create a virtual environment and install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Start the monitor script
python monitor.py
```

## Configure the Door Zone

1. Open Zone Picker: http://localhost:8090
2. Click on the camera feed to mark the corners of the door area
3. Copy the coordinates and paste into `config/frigate/config.yml` → `door_zone` → `coordinates`
4. `docker compose restart frigate`

## Project Structure

```
├── .env                          # 🔧 Unified config (IPs, ports, Bark key)
├── docker-compose.yml            # Frigate + Mosquitto + Zone Picker
├── monitor.py                    # Core logic (MQTT → Bark push)
├── zone-picker.html              # Visual zone coordinate picker
├── requirements.txt              # Python dependencies
├── config/
│   ├── frigate/config.yml        # Frigate detection & zone config
│   └── mosquitto/mosquitto.conf  # MQTT broker config
└── storage/                      # Persistent data (auto-generated)
```

## Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `MINI_IP` | Host machine LAN IP | `192.168.1.100` |
| `RTSP_URL` | IP Webcam RTSP address | — |
| `FRIGATE_PORT` | Frigate Web UI port | `5001` |
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
