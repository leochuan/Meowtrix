"""
Zone Picker backend — serves the HTML UI and handles zone save + Frigate restart.
Runs on port 80 inside the container.
"""

import http.server
import json
import os
import re
import urllib.request
import urllib.error

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/config.yml")
FRIGATE_URL = os.environ.get("FRIGATE_URL", "http://frigate:5000")
HTML_PATH = os.environ.get("HTML_PATH", "/app/index.html")


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/zone":
            self._get_zone()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/zone":
            self._save_zone()
        else:
            self.send_error(404)

    # --- handlers ---

    def _serve_html(self):
        try:
            with open(HTML_PATH, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(500, "HTML file not found")

    def _get_zone(self):
        """Return current zone coordinates from config."""
        try:
            with open(CONFIG_PATH, "r") as f:
                content = f.read()
            m = re.search(
                r"zones:\s+door_zone:\s+coordinates:\s*(.+)",
                content,
            )
            coords = m.group(1).strip() if m else ""
            self._json_response({"coordinates": coords})
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _save_zone(self):
        """Update zone coordinates in config and restart Frigate."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            coords = body.get("coordinates", "").strip()

            if not coords:
                self._json_response({"error": "coordinates required"}, 400)
                return

            # Validate format: comma-separated numbers between 0 and 1
            parts = coords.split(",")
            if len(parts) < 6 or len(parts) % 2 != 0:
                self._json_response({"error": "Need at least 3 points (6 values)"}, 400)
                return
            for p in parts:
                v = float(p)
                if not (0 <= v <= 1):
                    self._json_response({"error": f"Value out of range: {p}"}, 400)
                    return

            # Read and update config
            with open(CONFIG_PATH, "r") as f:
                content = f.read()

            new_content, count = re.subn(
                r"(zones:\s+door_zone:\s+coordinates:\s*).+",
                rf"\g<1>{coords}",
                content,
            )
            if count == 0:
                self._json_response({"error": "Could not find door_zone coordinates in config"}, 500)
                return

            with open(CONFIG_PATH, "w") as f:
                f.write(new_content)

            # Restart Frigate via API
            restart_ok = True
            restart_msg = "ok"
            try:
                req = urllib.request.Request(
                    f"{FRIGATE_URL}/api/restart",
                    method="POST",
                    data=b"",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    restart_msg = resp.read().decode()
            except Exception as e:
                restart_ok = False
                restart_msg = str(e)

            self._json_response({
                "saved": True,
                "coordinates": coords,
                "frigate_restarted": restart_ok,
                "restart_message": restart_msg,
            })

        except json.JSONDecodeError:
            self._json_response({"error": "Invalid JSON"}, 400)
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    # --- helpers ---

    def _json_response(self, data, code=200):
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[zone-picker] {fmt % args}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "80"))
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"[zone-picker] serving on :{port}")
    server.serve_forever()
