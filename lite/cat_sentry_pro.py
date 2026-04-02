#!/usr/bin/env python3
from __future__ import annotations

"""
Cat Sentry Pro — RTSP + YOLOv8 cat escape monitor with built-in Web UI.

Architecture:
  - Background thread: RTSP reader (always-latest-frame strategy)
  - Background thread: Sentry detection loop (motion gate -> YOLO -> alert)
  - Main thread: HTTP server serving the config/zone-picker Web UI + JSON API

All tunables live in config.json and can be changed at runtime via the Web UI.
Zone is a polygon (list of normalized [x, y] points) drawn on a live snapshot.
"""

import http.server
import json
import logging
import os
import socketserver
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Force RTSP over TCP — MUST be set before importing cv2
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import cv2
import numpy as np
import requests as req_lib
from ultralytics import YOLO

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("CatSentry")

# ---------------------------------------------------------------------------
# Resolve base path (PyInstaller-friendly)
# ---------------------------------------------------------------------------

def _base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent

BASE_DIR = _base_path()
CONFIG_PATH = BASE_DIR / "config.json"
HTML_PATH = BASE_DIR / "index.html"

# ---------------------------------------------------------------------------
# Config manager — thread-safe read/write of config.json
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "rtsp_url": "",
    "bark_urls": [],
    "snapshot_dir": "snapshots",
    "zone_points": [],
    "roi_padding_pct": 0.20,
    "motion_threshold": 5000,
    "yolo_model": "yolov8s.pt",
    "yolo_conf": 0.45,
    "alert_cooldown_sec": 10,
    "cat_class_id": 15,
    "web_port": 8080,
    "server_host": "",
    "sentry_enabled": True,
}

_config_lock = threading.Lock()
_config: dict = {}


def load_config() -> dict:
    """Load config from disk, merging with defaults."""
    global _config
    with _config_lock:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                on_disk = json.load(f)
        else:
            on_disk = {}
        _config = {**DEFAULT_CONFIG, **on_disk}
        return _config.copy()


def save_config(new_cfg: dict) -> dict:
    """Validate, merge, persist, and return the updated config."""
    global _config
    with _config_lock:
        merged = {**_config, **new_cfg}
        # Basic validation
        if not isinstance(merged.get("zone_points"), list):
            merged["zone_points"] = []
        merged["roi_padding_pct"] = max(0.0, min(1.0, float(merged["roi_padding_pct"])))
        merged["yolo_conf"] = max(0.01, min(1.0, float(merged["yolo_conf"])))
        merged["motion_threshold"] = max(0, int(merged["motion_threshold"]))
        merged["alert_cooldown_sec"] = max(0, int(merged["alert_cooldown_sec"]))
        merged["cat_class_id"] = int(merged["cat_class_id"])

        with open(CONFIG_PATH, "w") as f:
            json.dump(merged, f, indent=2)
        _config = merged
        log.info("Config saved to %s", CONFIG_PATH)
        return _config.copy()


def get_config() -> dict:
    with _config_lock:
        return _config.copy()

# ---------------------------------------------------------------------------
# Hardware acceleration
# ---------------------------------------------------------------------------

def select_device() -> str:
    import torch
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        log.info("Using MPS (Apple Silicon) acceleration")
        return "mps"
    if torch.cuda.is_available():
        log.info("Using CUDA acceleration")
        return "0"
    log.info("Using CPU")
    return "cpu"

# ---------------------------------------------------------------------------
# Threaded RTSP reader — always holds the *latest* frame
# ---------------------------------------------------------------------------


class RTSPReader:
    def __init__(self, url: str):
        self.url = url
        self._cap = self._open(url)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {url}")
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("RTSP reader started: %s", url)

    @staticmethod
    def _open(url: str) -> cv2.VideoCapture:
        """Open RTSP with TCP transport to avoid UDP packet-loss decode errors."""
        # Pass timeout params in constructor so they apply during open()
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000,
        ])
        # Minimal buffer to reduce latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _loop(self) -> None:
        fail_count = 0
        MAX_CONSECUTIVE_FAILS = 60  # tolerate ~6s of bad frames before reconnecting
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                fail_count += 1
                if fail_count >= MAX_CONSECUTIVE_FAILS:
                    log.warning("Frame grab failed %d times, reconnecting …", fail_count)
                    self._cap.release()
                    time.sleep(2)
                    self._cap = self._open(self.url)
                    fail_count = 0
                else:
                    time.sleep(0.1)  # yield CPU while skipping bad frames
                continue
            fail_count = 0
            with self._lock:
                self._frame = frame

    def read(self) -> np.ndarray | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self) -> None:
        self._running = False
        self._thread.join(timeout=3)
        self._cap.release()
        log.info("RTSP reader stopped")

# ---------------------------------------------------------------------------
# Polygon zone helpers
# ---------------------------------------------------------------------------

def polygon_to_pixel(zone_points: list[list[float]], h: int, w: int) -> np.ndarray:
    """Convert normalized [[x,y], …] to pixel coords numpy array (N,1,2) int32."""
    pts = np.array([[int(p[0] * w), int(p[1] * h)] for p in zone_points], dtype=np.int32)
    return pts.reshape((-1, 1, 2))


def polygon_bounding_box(zone_points: list[list[float]], h: int, w: int) -> tuple[int, int, int, int]:
    """Return (x1, y1, x2, y2) bounding box of the polygon in pixel coords."""
    pts = polygon_to_pixel(zone_points, h, w)
    x1, y1 = pts[:, 0, :].min(axis=0)
    x2, y2 = pts[:, 0, :].max(axis=0)
    return int(x1), int(y1), int(x2), int(y2)


def expand_roi(bbox: tuple[int, int, int, int], padding: float, h: int, w: int) -> tuple[int, int, int, int]:
    """Expand a bounding box by `padding` fraction, clamped to frame."""
    x1, y1, x2, y2 = bbox
    pw = int((x2 - x1) * padding)
    ph = int((y2 - y1) * padding)
    return max(x1 - pw, 0), max(y1 - ph, 0), min(x2 + pw, w), min(y2 + ph, h)


def point_in_polygon(px: int, py: int, poly_px: np.ndarray) -> bool:
    """Check if a point is inside the polygon using OpenCV."""
    return cv2.pointPolygonTest(poly_px, (float(px), float(py)), False) >= 0


def box_overlaps_polygon(bx1: int, by1: int, bx2: int, by2: int, poly_px: np.ndarray) -> bool:
    """Check if a bounding box overlaps a polygon (center or corners test)."""
    cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
    test_pts = [(cx, cy), (bx1, by1), (bx2, by1), (bx1, by2), (bx2, by2)]
    return any(point_in_polygon(x, y, poly_px) for x, y in test_pts)

# ---------------------------------------------------------------------------
# Motion detector
# ---------------------------------------------------------------------------

class MotionDetector:
    def __init__(self, threshold: int = 5000):
        self._prev_gray: np.ndarray | None = None
        self.threshold = threshold

    def detect(self, roi_bgr: np.ndarray) -> bool:
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self._prev_gray is None:
            self._prev_gray = gray
            return False
        diff = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray
        return int(np.sum(diff > 25)) > self.threshold

# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------

def save_snapshot(frame: np.ndarray, snapshot_dir: str,
                  detections: list[tuple[int, int, int, int, float]] | None = None,
                  zone_poly: np.ndarray | None = None) -> str:
    """Save annotated full-frame snapshot. Returns the file path.

    detections: list of (x1, y1, x2, y2, confidence)
    zone_poly: pixel polygon array (N,1,2) to draw the zone outline
    """
    annotated = frame.copy()

    # Draw zone polygon
    if zone_poly is not None:
        cv2.polylines(annotated, [zone_poly], isClosed=True, color=(0, 255, 255), thickness=2)

    # Draw detection boxes + confidence
    if detections:
        for (bx1, by1, bx2, by2, conf) in detections:
            cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (0, 0, 255), 2)
            label = f"cat {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(annotated, (bx1, by1 - th - 8), (bx1 + tw + 4, by1), (0, 0, 255), -1)
            cv2.putText(annotated, label, (bx1 + 2, by1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

    Path(snapshot_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = str(Path(snapshot_dir) / f"cat_alert_{ts}.jpg")
    cv2.imwrite(fp, annotated)
    log.info("Snapshot saved: %s", fp)
    return fp


def send_bark(bark_urls: list[str], title: str, body: str,
              image_path: str | None = None) -> None:
    if not bark_urls:
        return
    # Build image URL for Bark (served by our own HTTP server)
    image_url = ""
    if image_path:
        cfg = get_config()
        port = cfg.get("web_port", 8080)
        host = cfg.get("server_host", "")
        filename = Path(image_path).name
        if host:
            image_url = f"http://{host}:{port}/snapshots/{filename}"

    for bark_url in bark_urls:
        bark_url = bark_url.strip()
        if not bark_url:
            continue
        url = bark_url.rstrip("/")
        try:
            payload: dict = {
                "title": title,
                "body": body,
                "group": "CatSentry",
            }
            if image_url:
                payload["image"] = image_url
            resp = req_lib.post(url, json=payload, timeout=10)
            if resp.ok:
                log.info("Bark notification sent to %s", url)
            else:
                log.warning("Bark %s responded %s: %s", url, resp.status_code, resp.text[:200])
        except req_lib.RequestException as exc:
            log.error("Bark push to %s failed: %s", url, exc)


# ---------------------------------------------------------------------------
# Sentry engine — runs in its own thread
# ---------------------------------------------------------------------------

class SentryEngine:
    """Detection loop: motion gate -> YOLO -> polygon collision -> alert."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False
        self._reader: RTSPReader | None = None
        self._model: YOLO | None = None
        self._device: str = "cpu"
        self.status: str = "stopped"
        self.last_alert_time: float = 0.0
        self.alert_count: int = 0
        self._cat_was_in_zone: bool = False  # state machine: True while cat is inside

    def start(self) -> str:
        """Start or restart the sentry loop. Returns status message."""
        cfg = get_config()
        if not cfg["rtsp_url"]:
            self.status = "error: no RTSP URL"
            return self.status
        if len(cfg["zone_points"]) < 3:
            self.status = "error: need at least 3 zone points"
            return self.status

        self.stop()

        self._device = select_device()
        model_name = cfg.get("yolo_model", "yolov8s.pt")
        model_path = str(BASE_DIR / model_name)
        log.info("Loading YOLO model: %s", model_path)
        self._model = YOLO(model_path)

        self._reader = RTSPReader(cfg["rtsp_url"])
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.status = "running"
        log.info("Sentry engine started")
        return self.status

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._reader:
            self._reader.stop()
            self._reader = None
        self._model = None
        self.status = "stopped"
        log.info("Sentry engine stopped")

    def _loop(self) -> None:
        motion = MotionDetector()
        while self._running:
            cfg = get_config()
            motion.threshold = cfg["motion_threshold"]

            if not cfg["sentry_enabled"]:
                time.sleep(1)
                continue

            frame = self._reader.read() if self._reader else None
            if frame is None:
                time.sleep(0.05)
                continue

            h, w = frame.shape[:2]
            zone_pts = cfg["zone_points"]
            if len(zone_pts) < 3:
                time.sleep(1)
                continue

            # Compute ROI from polygon bounding box + padding
            bbox = polygon_bounding_box(zone_pts, h, w)
            rx1, ry1, rx2, ry2 = expand_roi(bbox, cfg["roi_padding_pct"], h, w)
            roi_crop = frame[ry1:ry2, rx1:rx2]

            if roi_crop.size == 0:
                continue

            # Stage 1: motion gate
            if not motion.detect(roi_crop):
                continue

            log.info("Motion detected [%dx%d] ROI=(%d,%d)-(%d,%d)", w, h, rx1, ry1, rx2, ry2)

            # Stage 2: YOLO on ROI
            results = self._model.predict(
                roi_crop,
                conf=cfg["yolo_conf"],
                device=self._device,
                classes=[cfg["cat_class_id"]],
                verbose=False,
            )
            boxes = results[0].boxes
            if boxes is None or len(boxes) == 0:
                log.info("  YOLO: no cat")
                continue

            # Stage 3: polygon collision — collect all detections
            poly_px = polygon_to_pixel(zone_pts, h, w)
            cat_in_zone = False
            detections: list[tuple[int, int, int, int, float]] = []
            for box in boxes:
                bx1, by1, bx2, by2 = box.xyxy[0].cpu().numpy()
                abs_bx1 = int(bx1) + rx1
                abs_by1 = int(by1) + ry1
                abs_bx2 = int(bx2) + rx1
                abs_by2 = int(by2) + ry1
                conf = float(box.conf[0])
                detections.append((abs_bx1, abs_by1, abs_bx2, abs_by2, conf))
                log.info("  Cat conf=%.2f bbox=(%d,%d)-(%d,%d)", conf, abs_bx1, abs_by1, abs_bx2, abs_by2)
                if box_overlaps_polygon(abs_bx1, abs_by1, abs_bx2, abs_by2, poly_px):
                    cat_in_zone = True

            if not cat_in_zone:
                log.info("  Cat outside zone")
                if self._cat_was_in_zone:
                    log.info("  Cat left the zone — armed for next entry")
                    self._cat_was_in_zone = False
                continue

            # Stage 4: state machine — only alert on fresh entry
            if self._cat_was_in_zone:
                # Cat is still inside from a previous detection, no re-alert
                continue

            self._cat_was_in_zone = True
            self.alert_count += 1
            log.warning("*** ALERT: Cat entered forbidden zone! ***")
            snap_path = save_snapshot(frame, cfg["snapshot_dir"],
                                      detections=detections, zone_poly=poly_px)
            alert_time = datetime.now().strftime('%H:%M:%S')
            send_bark(
                cfg["bark_urls"],
                "猫咪越狱警报",
                f"猫咪闯入禁区！时间：{alert_time}",
                image_path=snap_path,
            )

# Global sentry instance
sentry = SentryEngine()

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

# Shared preview reader for MJPEG streams (auto-managed, single instance)
_preview_lock = threading.Lock()
_preview_reader: RTSPReader | None = None
_preview_clients = 0


def _acquire_stream() -> None:
    """Register an MJPEG client. Opens preview reader if sentry isn't running."""
    global _preview_reader, _preview_clients
    with _preview_lock:
        _preview_clients += 1
        if sentry._reader is None and _preview_reader is None:
            cfg = get_config()
            if cfg["rtsp_url"]:
                try:
                    _preview_reader = RTSPReader(cfg["rtsp_url"])
                except RuntimeError:
                    pass


def _release_stream() -> None:
    """Unregister an MJPEG client. Stops preview reader when no clients remain."""
    global _preview_reader, _preview_clients
    with _preview_lock:
        _preview_clients = max(0, _preview_clients - 1)
        if _preview_clients == 0 and _preview_reader is not None:
            _preview_reader.stop()
            _preview_reader = None


def _current_reader() -> RTSPReader | None:
    """Get the best available reader right now. Sentry reader takes priority."""
    global _preview_reader
    # Prefer sentry's reader — also release preview if sentry took over
    if sentry._reader is not None:
        with _preview_lock:
            if _preview_reader is not None:
                _preview_reader.stop()
                _preview_reader = None
        return sentry._reader
    return _preview_reader


class SentryHandler(http.server.BaseHTTPRequestHandler):
    """Serves Web UI + JSON API for config, snapshots, and sentry control."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(HTML_PATH, "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._json_ok(get_config())
        elif self.path == "/api/status":
            self._json_ok({
                "sentry": sentry.status,
                "alert_count": sentry.alert_count,
                "last_alert": sentry.last_alert_time,
            })
        elif self.path.startswith("/api/snapshot"):
            self._serve_snapshot()
        elif self.path.startswith("/api/stream"):
            self._serve_mjpeg()
        elif self.path.startswith("/snapshots/"):
            self._serve_alert_image()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/config":
            self._update_config()
        elif self.path == "/api/sentry/start":
            msg = sentry.start()
            self._json_ok({"status": msg})
        elif self.path == "/api/sentry/stop":
            sentry.stop()
            self._json_ok({"status": "stopped"})
        else:
            self.send_error(404)

    # --- handlers ---

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(500, "File not found")

    def _serve_alert_image(self) -> None:
        """Serve saved alert snapshot images from /snapshots/<filename>."""
        # Sanitize: only allow filenames, no path traversal
        filename = self.path.split("/snapshots/", 1)[-1]
        if "/" in filename or ".." in filename:
            self.send_error(403)
            return
        cfg = get_config()
        filepath = Path(cfg["snapshot_dir"]) / filename
        if not filepath.exists():
            self.send_error(404)
            return
        self._serve_file(filepath, "image/jpeg")

    def _serve_snapshot(self) -> None:
        """Return latest RTSP frame as JPEG."""
        reader = sentry._reader
        if reader is None:
            # Try to grab a one-shot frame from config RTSP URL
            cfg = get_config()
            if not cfg["rtsp_url"]:
                self._json_err("No RTSP URL configured", 400)
                return
            cap = RTSPReader._open(cfg["rtsp_url"])
            # RTSP needs a few frames to stabilize after TCP handshake
            frame = None
            for _ in range(30):
                ok, f = cap.read()
                if ok:
                    frame = f
                    break
            cap.release()
            if frame is None:
                self._json_err("Cannot grab frame from RTSP", 502)
                return
        else:
            frame = reader.read()
            if frame is None:
                self._json_err("No frame available yet", 503)
                return

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        data = buf.tobytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_mjpeg(self) -> None:
        """Stream MJPEG over HTTP (multipart/x-mixed-replace)."""
        BOUNDARY = b"--frame"
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()

        _acquire_stream()
        try:
            while True:
                reader = _current_reader()
                if reader is None:
                    time.sleep(0.5)
                    continue
                frame = reader.read()
                if frame is None:
                    time.sleep(0.05)
                    continue
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                jpg = buf.tobytes()
                try:
                    self.wfile.write(BOUNDARY + b"\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode())
                    self.wfile.write(jpg)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.1)  # ~10 fps cap
        finally:
            _release_stream()

    def _update_config(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            updated = save_config(body)
            self._json_ok(updated)
        except json.JSONDecodeError:
            self._json_err("Invalid JSON", 400)
        except Exception as e:
            self._json_err(str(e), 500)

    # --- helpers ---

    def _json_ok(self, data: dict) -> None:
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json_err(self, msg: str, code: int) -> None:
        payload = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        log.debug("[HTTP] " + fmt, *args)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main() -> None:
    cfg = load_config()
    port = int(os.environ.get("PORT", cfg.get("web_port", 8080)))

    # Auto-start sentry if RTSP URL is configured and zone is defined
    if cfg["rtsp_url"] and len(cfg["zone_points"]) >= 3 and cfg["sentry_enabled"]:
        log.info("Auto-starting sentry engine …")
        sentry.start()

    server = ThreadedHTTPServer(("0.0.0.0", port), SentryHandler)
    log.info("Web UI available at http://0.0.0.0:%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down …")
    finally:
        sentry.stop()
        server.server_close()


if __name__ == "__main__":
    main()
