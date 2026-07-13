# BlueOS ESPHome — Device Builder + `blueos-relay` factory project

A BlueOS extension that bundles the **ESPHome Device Builder** (compile / OTA /
USB-flash UI) together with a ready-to-go **`blueos-relay`** project for the
Waveshare **ESP32-S3-Relay-6CH** + **Pico-RTC-DS3231**. Install this only when
you need to flash or reconfigure that board — it is not required for runtime
relay control or telemetry (that's `blueos-site-stack` + `blueos-site-ui`).

```text
blueos-site-esphome (this extension)
  ├─ ESPHome Device Builder dashboard  :6052  — compile / USB flash / OTA install
  └─ BlueOS setup wizard               :80    — Beacon hostname → MQTT broker,
                                                 Wi-Fi credentials, API/OTA secrets
```

## Why this exists

Operators should never hand-edit a broker IP into firmware. The factory YAML
uses `!secret mqtt_broker`, and the wizard fills that secret from the **live**
BlueOS hostname — never a hardcoded `blueos.local`.

## Setup wizard (Beacon hostname injection)

Open the extension ("Open" in BlueOS Extensions → this image) to reach the
wizard on port 80. The wizard also serves `/register_service` so **ESPHome Site**
appears in the BlueOS sidebar
([docs](https://blueos.cloud/docs/latest/development/extensions/#web-interface-http-server)):

1. **MQTT broker** — the wizard calls BlueOS **Beacon** at
   `http://host.docker.internal:9111/v1.0/hostname` (reachable via the
   `ExtraHosts: host.docker.internal:host-gateway` permission, same pattern as
   `blueos-mosquitto` / `blueos-influxdb`). Beacon's `GET /v1.0/hostname`
   returns the vehicle's current mDNS label (default `blueos`, or whatever the
   operator renamed it to in BlueOS → Vehicle setup) as a bare JSON string. The
   wizard proposes `{hostname}.local` as the broker, and also queries
   `GET /v1.0/services` to look for a Wi‑Fi-specific advertised name
   (`{hostname}-wifi.local`) since the ESP joins the site Wi‑Fi, not a wired
   link. Both show up in a dropdown; a free-text field lets you override with
   a static IP (e.g. `192.168.1.113`) if mDNS is unreliable on that LAN —
   Beacon's own `/v1.0/ip` endpoint only resolves a caller's *own* interface
   IP through BlueOS's nginx proxy headers, so it isn't a reliable way to
   guess the Pi's LAN IP from inside a container; a manual override is the
   correct fallback here.
2. **Wi‑Fi SSID / password** — the one thing that can't be auto-detected;
   typed once into the wizard.
3. **API / OTA secrets** — `api_encryption_key` (32 random bytes, base64) and
   `ota_password` (random hex) are generated automatically the first time you
   save, and kept stable afterwards unless you explicitly check "regenerate".

Saving writes `/config/secrets.yaml` (bind-mounted, persists across container
restarts/updates) and seeds `/config/blueos-relay.yaml` from the bundled
factory project if it isn't already there.

Re-running the wizard after renaming the vehicle in BlueOS re-injects the new
hostname — no reflash required if the device is already reachable
(OTA picks up the new broker on its next boot/reconnect once you push the
updated config).

## Flashing

### First flash (blank / new board) — USB required

1. Plug the ESP32 directly into a **USB port on the BlueOS Pi** (not your
   laptop) — the extension flashes from *inside* the Pi's Docker network.
2. In the wizard, click **Refresh USB devices**. The ESP32-S3's native
   USB-CDC typically shows up as `/dev/ttyACM0`; USB-JTAG mode has been flaky
   on some boards in testing — unplug/replug or try another port/cable if
   nothing appears.
3. Click **Open ESPHome Dashboard →**, pick `blueos-relay.yaml`, and use
   **Install** with the detected serial port.

### Reconfigure / re-flash an already-running device — OTA, no USB

If the ESP is already on the network (e.g. the test unit at `192.168.1.166`),
save the wizard config, open the dashboard, and **Install** targeting `OTA`
(or the device's IP/hostname directly) — no USB, no Pi access needed. This is
the expected path for most day-2 changes (Wi‑Fi password rotation, broker
rename after a BlueOS hostname change, YAML tweaks).

## USB permissions

The ESP32-S3's serial device node isn't predictable ahead of time (varies by
hub, board revision, and hotplug order — could be `/dev/ttyACM0`,
`/dev/ttyUSB0`, etc.), so this extension requests:

```json
"HostConfig": {
  "Privileged": true,
  "Binds": ["/dev:/dev"]
}
```

This grants the container access to whatever serial device shows up, rather
than guessing a fixed path. **OTA reflashing needs none of this** — only
first-flash-over-USB does. If your BlueOS security posture disallows
`Privileged`, you can still use the extension purely for the wizard + OTA path
and drop that permission (edit the extension's custom settings after install).

## Manual install on BlueOS

Open BlueOS → **Extensions** → **Installed** → **+** and fill these fields
exactly:

| Field | Value |
|-------|--------|
| **Extension Identifier** | `vshie.esphome` |
| **Extension Name** | `ESPHome Device Builder` |
| **Docker image** | `vshie/blueos-site-esphome` |
| **Docker tag** | `main` |

**Custom settings** — paste this JSON **verbatim** into the permissions /
custom-settings box (USB flash + Beacon hostname + persistent config):

```json
{
  "ExposedPorts": {
    "80/tcp": {},
    "6052/tcp": {}
  },
  "HostConfig": {
    "Privileged": true,
    "ExtraHosts": ["host.docker.internal:host-gateway"],
    "PortBindings": {
      "80/tcp": [
        {
          "HostPort": ""
        }
      ],
      "6052/tcp": [
        {
          "HostPort": "6052"
        }
      ]
    },
    "Binds": [
      "/usr/blueos/extensions/esphome:/config",
      "/dev:/dev"
    ]
  }
}
```

What each piece does:

| Setting | Why |
|---------|-----|
| `Privileged` + `/dev:/dev` | USB serial for first-flash (ESP32-S3 path varies) |
| `ExtraHosts: host.docker.internal:host-gateway` | Wizard → Beacon `GET :9111/v1.0/hostname` |
| Host port `6052` | ESPHome Device Builder dashboard |
| Dynamic host port for `80` | Setup wizard (“Open” in Extensions) |
| `/usr/blueos/extensions/esphome:/config` | Persists `blueos-relay.yaml` + `secrets.yaml` |

**After install**

1. Click **Open** on the extension → setup wizard (Beacon broker + Wi‑Fi + secrets).
2. Dashboard: `http://<blueos-ip>:6052`
3. Safe to run alongside **`blueos-site-stack`**: stack owns `1883` / `9001` / `8086`; this extension owns `6052` (+ a dynamic wizard port). No port overlap.

## Ports

| Port | Binding | Use |
|------|---------|-----|
| `80` | Dynamic | BlueOS setup wizard (Beacon inject, Wi‑Fi, secrets) |
| `6052` | Host `6052` | ESPHome Device Builder dashboard (compile/flash/OTA/logs) |

## Bundled project — `blueos-relay.yaml`

Waveshare ESP32-S3-Relay-6CH + Pico-RTC-DS3231, pre-filled so the operator
never starts from a blank ESPHome project:

- 6× relay switches, boot button, buzzer, status RGB LED
- DS3231 RTC via `ds1307` platform (I2C `GPIO4`/`GPIO5`) — offline clock of
  record; SNTP writes wall time back to the chip when online, and the chip
  is periodically re-read (`update_interval: 6h`) to correct ESP32 internal
  clock drift even when the device never gets internet
- **Per-relay daily on/off scheduler** (`schedule.h`, edge-triggered against
  `id(rtc_time).now()`) — see [MQTT schedule schema](#mqtt-schedule-schema)
  below. Config is set/read entirely over MQTT retained messages; no flash
  writes on the ESP side.
- `RTC Temperature` template sensor (chip's onboard temp register)
- `RTC Epoch` template sensor (Unix seconds from the RTC-backed system
  clock) — consumed by `blueos-site-stack`'s time-from-RTC sidecar and
  graphable in Grafana
- `RTC DateTime` template text sensor (human-readable wall time) — added so
  `blueos-site-ui` can show a status/debug table without extra tooling
- `RTC Sync Now` momentary switch (MQTT-controllable; native `button:`
  entities have no MQTT topic) and `RTC Read from DS3231` / `RTC Write from
  ESP time` buttons (API/web_server only) for manual sync
- MQTT `topic_prefix: blueos/relay` — **coordinated with `blueos-site-stack`
  (Telegraf topic subscription pattern `blueos/+/sensor|switch|binary_sensor/+/state`
  and `blueos/+/status`) and `blueos-site-ui` (control page / Grafana
  datasource)**. Don't change this without updating those extensions too.
- `mqtt.broker: !secret mqtt_broker` — filled by this extension's wizard, not
  hardcoded
- `schedule.h` (bundled alongside `blueos-relay.yaml`, referenced via
  `esphome.includes`) — shared scheduler logic. The wizard re-seeds this file
  from the image on every start so extension updates pick up scheduler fixes
  without touching your `blueos-relay.yaml`/`secrets.yaml`.

### MQTT schedule schema

Per-relay daily on/off window, set and read entirely over MQTT (no HA, no
flash writes on the ESP — the broker's retained `/set` message *is* the
durable copy, replayed to the device on every reconnect/reboot):

| Topic | Direction | Payload |
|-------|-----------|---------|
| `blueos/relay/schedule/relay_<N>/set` | site-ui → ESP (retain) | `{"enabled":bool,"on":"HH:MM","off":"HH:MM","days":"SMTWTFS"}` |
| `blueos/relay/schedule/relay_<N>/state` | ESP → broker (retain) | Same shape — echoed after every `/set` and on every MQTT (re)connect |

`N` is `1`–`6`. `days` is a 7-character string, index 0 = Sunday .. index 6 =
Saturday, `'1'` = active that day (all fields except `enabled` are optional
per-message — omit `days` to leave the existing day mask untouched, etc.).
A window where `off` < `on` wraps past midnight; the day mask is evaluated
against the day the window **starts** on.

The engine is edge-triggered: it only calls `switch.turn_on`/`turn_off` when
the scheduled window transitions, so a manual override via
`blueos/relay/switch/relay_<N>/command` between two edges is left alone
until the next scheduled transition — Home-Assistant-style "the schedule
doesn't fight your manual click".

Full topic map (unchanged entities + new ones from this iteration):

| Entity | Domain (MQTT) | Topic (state) | Notes |
|--------|--------|----------------|-------|
| Relay 1–6 | switch | `blueos/relay/switch/relay_N/state` | Command: `ON`/`OFF` — also driven by the scheduler |
| RTC Sync Now | switch (momentary) | `blueos/relay/switch/rtc_sync_now/state` | Command `ON` → writes current system time to DS3231 |
| RTC Temperature | sensor | `blueos/relay/sensor/rtc_temperature/state` | °C |
| RTC Epoch | sensor | `blueos/relay/sensor/rtc_epoch/state` | Unix seconds |
| RTC DateTime | **sensor** (not `text_sensor` — see note) | `blueos/relay/sensor/rtc_datetime/state` | `YYYY-MM-DD HH:MM:SS` |
| Firmware/IP/SSID/MAC | **sensor** (not `text_sensor`) | `blueos/relay/sensor/<name>/state` | Read-only strings |
| Schedule relay_N | — (custom JSON) | `blueos/relay/schedule/relay_N/state` / `.../set` | See table above |
| Device availability | — | `blueos/relay/status` | `online`/`offline` (LWT) |

> **ESPHome MQTT quirk:** all `text_sensor:` entities publish under the
> `sensor` MQTT topic segment, not `text_sensor` — ESPHome's
> `MQTTTextSensor` component registers itself with component type `"sensor"`
> (see `esphome/components/mqtt/mqtt_text_sensor.cpp`). `blueos-site-ui`'s
> device seed accounts for this.

> **Note:** `blueos-site-stack`'s Telegraf only subscribes to
> `sensor`/`switch`/`binary_sensor`/`status` topics for InfluxDB history (see
> its `config/telegraf.conf`) — `text_sensor` values like `RTC DateTime` and
> `Firmware Version` are **not** historized in Influx by default. They're
> still visible over MQTT (and the ESPHome native API / web_server) for
> `blueos-site-ui` to display live, just not graphed. Add an
> `inputs.mqtt_consumer` block for `+/text_sensor/+/state` in that repo if you
> want them in Influx too.

This same YAML is developed alongside `BlueOS-HA-node/esphome/blueos-relay.yaml`
on the workstation repo; the `RTC DateTime` sensor added here has been synced
back there too.

## Building / releasing

| Platform | Hardware |
|----------|----------|
| `linux/arm64/v8` | Pi 4 (64-bit), **Pi 5** |
| `linux/amd64` | Desktop / CI |
| `linux/arm/v7` | **Not built** — the upstream `esphome/esphome` image dropped arm/v7 support (Pi 3B+ / 32-bit Pi 4 would need cross-compiling ESPHome's own toolchain, which is unrealistic to maintain here). Pi 3B+ users should use a 64-bit Pi 4/5 for this extension, or flash `blueos-relay.yaml` from a laptop with `esphome` installed directly. |

**CI secrets:** https://github.com/vshie/blueos-site-esphome/settings/secrets/actions

- `DOCKER_USERNAME` = `vshie`
- `DOCKER_PASSWORD` = Docker Hub [access token](https://hub.docker.com/settings/security)

Published image: **`vshie/blueos-site-esphome:main`** (also tagged per git tag / SemVer).

CI builds **arm64 + amd64 only** (custom workflow — upstream ESPHome has no
`arm/v7` image, and `Deploy-BlueOS-Extension@v1.2.0` always tries an arm/v7
artifact after push).

## Secrets — local dev, not committed

`config/secrets.yaml` is git-ignored. Use `config/secrets.yaml.example` as the
template; the wizard writes the real file onto the extension's persistent
volume (`/usr/blueos/extensions/esphome/secrets.yaml` on the BlueOS host) at
runtime. Never commit real Wi‑Fi credentials, API keys, or OTA passwords.

## Provenance

| Layer | Source |
|-------|--------|
| ESPHome + Device Builder dashboard | Official [`esphome/esphome`](https://hub.docker.com/r/esphome/esphome) image |
| Setup wizard | This repo (Python stdlib + PyYAML, no extra deps) |
| `blueos-relay.yaml` | This repo, developed alongside `BlueOS-HA-node/esphome/blueos-relay.yaml` |

## Product stack alignment

See workstation `BlueOS-HA-node/PLAN.md`. Operator-facing target:

1. `blueos-site-stack` — Mosquitto + InfluxDB + Telegraf
2. `blueos-site-ui` — Grafana + relay control page (publishes to
   `blueos/relay/switch/relay_*/command`, expects `blueos/relay/status`,
   `blueos/relay/sensor/rtc_temperature/state`, and now
   `blueos/relay/sensor/rtc_datetime/state`)
3. **`blueos-site-esphome`** (this repo) — Device Builder + bundled
   `blueos-relay` + Beacon hostname inject + USB prompt

Only install this extension when flashing/onboarding hardware; leave it
uninstalled (or stopped) the rest of the time to save Pi resources — ESPHome's
toolchain image is large.

## License

Packaging: community BlueOS extension conventions. ESPHome: upstream
ESPHome license (MIT-style, see [esphome/esphome](https://github.com/esphome/esphome)).
