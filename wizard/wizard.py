#!/usr/bin/env python3
"""BlueOS setup wizard for the blueos-site-esphome extension.

Serves a small UI + JSON API on STATUS_PORT (BlueOS "Open" button). Its job is
narrow on purpose: seed the bundled blueos-relay ESPHome project, inject the
live BlueOS hostname (via Beacon) as the MQTT broker instead of a hardcoded
`blueos.local`, collect Wi-Fi credentials, and generate API/OTA secrets. The
actual compile/flash UX is the bundled ESPHome Device Builder dashboard
(separate process, DASHBOARD_PORT) — this wizard links to it rather than
reimplementing it.
"""

import base64
import glob
import json
import os
import secrets as secretsmod
import shutil
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

CONFIG_DIR = os.environ.get("ESPHOME_CONFIG_DIR", "/config")
WWW_DIR = os.environ.get("WWW_DIR", "/opt/blueos/www")
FACTORY_DIR = os.environ.get("FACTORY_DIR", "/opt/blueos/factory")
STATUS_PORT = int(os.environ.get("STATUS_PORT", "80"))
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "6052"))
BEACON_HOST = os.environ.get("BEACON_HOST", "host.docker.internal")
BEACON_PORT = os.environ.get("BEACON_PORT", "9111")
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "blueos/relay")
PROJECT_NAME = "blueos-relay"

SECRETS_PATH = os.path.join(CONFIG_DIR, "secrets.yaml")
YAML_PATH = os.path.join(CONFIG_DIR, f"{PROJECT_NAME}.yaml")
FACTORY_YAML = os.path.join(FACTORY_DIR, f"{PROJECT_NAME}.yaml")
FACTORY_SECRETS_EXAMPLE = os.path.join(FACTORY_DIR, "secrets.yaml.example")
# blueos-relay.yaml's `esphome.includes` pulls this in for the relay
# scheduler (see blueos-site-ui's "MQTT schedule schema" docs) — must live
# next to the .yaml in /config for the ESPHome compiler to find it.
SCHEDULE_HEADER = "schedule.h"
FACTORY_SCHEDULE_HEADER = os.path.join(FACTORY_DIR, SCHEDULE_HEADER)

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def ensure_seeded() -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(YAML_PATH) and os.path.exists(FACTORY_YAML):
        shutil.copy(FACTORY_YAML, YAML_PATH)
    if not os.path.exists(SECRETS_PATH) and os.path.exists(FACTORY_SECRETS_EXAMPLE):
        shutil.copy(FACTORY_SECRETS_EXAMPLE, SECRETS_PATH)
    # Always refresh the bundled schedule.h from the image (it has no user
    # data — safe to overwrite on every start so extension updates pick up
    # scheduler fixes without touching blueos-relay.yaml/secrets.yaml).
    schedule_dest = os.path.join(CONFIG_DIR, SCHEDULE_HEADER)
    if os.path.exists(FACTORY_SCHEDULE_HEADER):
        shutil.copy(FACTORY_SCHEDULE_HEADER, schedule_dest)


def load_secrets() -> dict:
    if not os.path.exists(SECRETS_PATH):
        return {}
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_secrets(data: dict) -> None:
    os.makedirs(os.path.dirname(SECRETS_PATH), exist_ok=True)
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        f.write(
            "# Managed by the blueos-site-esphome setup wizard.\n"
            "# Safe to hand-edit; the wizard only rewrites keys you submit.\n"
            "# NOT committed to git — see secrets.yaml.example for the template.\n"
        )
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def fetch_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_beacon(beacon_host: str, beacon_port: str) -> dict:
    """Query BlueOS Beacon for the live mDNS hostname.

    GET /v1.0/hostname returns a bare JSON string, e.g. "blueos" or "mysite"
    (see bluerobotics/BlueOS core/services/beacon/main.py). We never fall
    back to a hardcoded "blueos" host string for the broker — only for the
    UI placeholder when Beacon is unreachable.
    """
    base = f"http://{beacon_host}:{beacon_port}/v1.0"
    result = {
        "available": False,
        "hostname": None,
        "wifi_hostname": None,
        "candidates": [],
        "source": f"{beacon_host}:{beacon_port}",
        "error": None,
    }
    try:
        hostname = fetch_json(f"{base}/hostname")
        if not isinstance(hostname, str) or not hostname:
            raise ValueError("empty hostname from Beacon")
        result["available"] = True
        result["hostname"] = hostname
        candidates = [f"{hostname}.local"]

        wifi_hostname = None
        try:
            services = fetch_json(f"{base}/services")
            # Prefer Wi‑Fi names that match the *current* vehicle hostname.
            # Stale leftovers like "blueos-wifi" can still be advertised after a rename.
            wifi_names = sorted(
                {
                    s.get("hostname")
                    for s in services
                    if isinstance(s, dict)
                    and s.get("hostname")
                    and "wifi" in str(s.get("interface_type", "")).lower()
                    and str(s.get("hostname")).startswith(hostname)
                }
            )
            if wifi_names:
                wifi_hostname = wifi_names[0]
        except Exception:
            pass

        if not wifi_hostname:
            wifi_hostname = f"{hostname}-wifi"
        result["wifi_hostname"] = wifi_hostname
        # Put Wi‑Fi first: ESP boards on site LAN must not pick the tether IP
        # that bare "{hostname}.local" often resolves to (e.g. 192.168.2.2).
        candidates = [f"{wifi_hostname}.local", f"{hostname}.local"]
        # De-dupe while preserving order
        seen = set()
        result["candidates"] = [c for c in candidates if not (c in seen or seen.add(c))]
    except Exception as exc:  # noqa: BLE001 - report to UI, don't crash wizard
        result["error"] = str(exc)
    return result


def list_usb_devices() -> dict:
    ports = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    return {"ports": ports, "by_id": by_id}


def dashboard_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", DASHBOARD_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def build_status() -> dict:
    ensure_seeded()
    data = load_secrets()
    beacon = fetch_beacon(BEACON_HOST, BEACON_PORT)
    return {
        "project": PROJECT_NAME,
        "topic_prefix": MQTT_TOPIC_PREFIX,
        "config_dir": CONFIG_DIR,
        "yaml_exists": os.path.exists(YAML_PATH),
        "secrets_exists": os.path.exists(SECRETS_PATH),
        "beacon": beacon,
        "usb": list_usb_devices(),
        "dashboard_port": DASHBOARD_PORT,
        "dashboard_up": dashboard_reachable(),
        "current": {
            "wifi_ssid": data.get("wifi_ssid") or "",
            "wifi_password_set": bool(data.get("wifi_password")),
            "mqtt_broker": data.get("mqtt_broker") or "",
            "mqtt_username": data.get("mqtt_username") or "",
            "mqtt_password_set": bool(data.get("mqtt_password")),
            "api_encryption_key_set": bool(data.get("api_encryption_key")),
            "ota_password_set": bool(data.get("ota_password")),
        },
    }


def apply_configure(payload: dict) -> dict:
    ensure_seeded()
    data = load_secrets()

    ssid = (payload.get("wifi_ssid") or "").strip()
    password = payload.get("wifi_password") or ""
    broker = (payload.get("mqtt_broker") or "").strip()
    username = payload.get("mqtt_username")
    mqtt_password = payload.get("mqtt_password")

    if ssid:
        data["wifi_ssid"] = ssid
    if password:
        data["wifi_password"] = password
    if broker:
        data["mqtt_broker"] = broker
    if username is not None:
        data["mqtt_username"] = username
    if mqtt_password is not None:
        data["mqtt_password"] = mqtt_password

    if not data.get("api_encryption_key") or payload.get("regen_api_key"):
        data["api_encryption_key"] = base64.b64encode(os.urandom(32)).decode("ascii")
    if not data.get("ota_password") or payload.get("regen_ota_password"):
        data["ota_password"] = secretsmod.token_hex(16)

    data.setdefault("mqtt_username", "")
    data.setdefault("mqtt_password", "")

    save_secrets(data)

    if not os.path.exists(YAML_PATH) and os.path.exists(FACTORY_YAML):
        shutil.copy(FACTORY_YAML, YAML_PATH)

    return {
        "ok": True,
        "secrets_path": SECRETS_PATH,
        "yaml_path": YAML_PATH,
        "wifi_ssid": data.get("wifi_ssid", ""),
        "mqtt_broker": data.get("mqtt_broker", ""),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "BlueOSESPHomeWizard/0.1"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str, content_type: str) -> None:
        path = os.path.join(WWW_DIR, filename)
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": f"missing static file {filename}"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args) -> None:  # quieter default logging
        print(f"[wizard] {self.address_string()} {fmt % args}")

    def _path_only(self) -> str:
        return (self.path or "/").split("?", 1)[0]

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = self._path_only()
        # BlueOS sidebar registration:
        # https://blueos.cloud/docs/latest/development/extensions/#web-interface-http-server
        if path.rstrip("/") == "/register_service":
            self._send_json(
                {
                    "name": "ESP Setup",
                    "description": (
                        "Set up Wi‑Fi and mailbox for your ESP32 relay board, then flash it."
                    ),
                    "icon": "mdi-chip",
                    "company": "Community",
                    "version": "0.4.0",
                    "webpage": "https://github.com/vshie/blueos-site-esphome",
                    "api": "https://github.com/vshie/blueos-site-esphome/blob/main/README.md",
                    "new_page": False,
                    "works_in_relative_paths": True,
                }
            )
        elif path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            self._send_static(filename, content_type)
        elif path == "/api/status":
            try:
                self._send_json(build_status())
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        if self._path_only() != "/api/configure":
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON body"}, 400)
            return
        try:
            self._send_json(apply_configure(payload))
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, 500)


def main() -> None:
    ensure_seeded()
    server = ThreadingHTTPServer(("0.0.0.0", STATUS_PORT), Handler)
    print(f"[wizard] listening on :{STATUS_PORT} (config dir={CONFIG_DIR}, beacon={BEACON_HOST}:{BEACON_PORT})")
    server.serve_forever()


if __name__ == "__main__":
    main()
