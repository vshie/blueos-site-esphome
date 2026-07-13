#!/bin/bash
set -euo pipefail

CONFIG_DIR="${ESPHOME_CONFIG_DIR:-/config}"
FACTORY_DIR="${FACTORY_DIR:-/opt/blueos/factory}"
STATUS_PORT="${STATUS_PORT:-80}"
DASHBOARD_PORT="${DASHBOARD_PORT:-6052}"
PREWARM_ESPHOME_DIR="${PREWARM_ESPHOME_DIR:-/opt/blueos/prewarm/esphome}"

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/blueos-relay.yaml" ]; then
  echo "Seeding factory project blueos-relay.yaml -> $CONFIG_DIR"
  cp "$FACTORY_DIR/blueos-relay.yaml" "$CONFIG_DIR/blueos-relay.yaml"
fi

if [ ! -f "$CONFIG_DIR/secrets.yaml" ]; then
  echo "Seeding secrets.yaml.example -> $CONFIG_DIR/secrets.yaml (placeholders; use the wizard on :${STATUS_PORT} to fill in Wi-Fi + broker)"
  cp "$FACTORY_DIR/secrets.yaml.example" "$CONFIG_DIR/secrets.yaml"
fi

# Always refresh schedule.h from the image (no user data).
if [ -f "$FACTORY_DIR/schedule.h" ]; then
  cp "$FACTORY_DIR/schedule.h" "$CONFIG_DIR/schedule.h"
fi

# Seed PlatformIO/ESPHome object cache from the image on first use of this volume.
# /root/.platformio is already baked into the image (host-arch toolchains).
# /config/.esphome lives on the bind mount and would otherwise be empty → cold compile.
if [ -d "$PREWARM_ESPHOME_DIR/build" ] && [ ! -d "$CONFIG_DIR/.esphome/build/blueos-relay" ]; then
  echo "Seeding pre-warmed ESPHome build cache -> $CONFIG_DIR/.esphome (first boot)"
  mkdir -p "$CONFIG_DIR/.esphome"
  cp -a "$PREWARM_ESPHOME_DIR/." "$CONFIG_DIR/.esphome/"
fi

echo "Starting ESPHome Device Builder dashboard on :${DASHBOARD_PORT} (config dir: $CONFIG_DIR)..."
esphome dashboard "$CONFIG_DIR" --address 0.0.0.0 --port "$DASHBOARD_PORT" &
DASHBOARD_PID=$!

echo "Starting BlueOS setup wizard on :${STATUS_PORT}..."
python3 /opt/blueos/wizard.py &
WIZARD_PID=$!

shutdown() {
  echo "Shutting down..."
  kill "$DASHBOARD_PID" "$WIZARD_PID" 2>/dev/null || true
  wait "$DASHBOARD_PID" "$WIZARD_PID" 2>/dev/null || true
}
trap shutdown INT TERM

while kill -0 "$DASHBOARD_PID" 2>/dev/null && kill -0 "$WIZARD_PID" 2>/dev/null; do
  sleep 2
done

echo "A child process exited; shutting down." >&2
shutdown
exit 1
