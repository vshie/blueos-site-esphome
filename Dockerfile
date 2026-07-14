# BlueOS extension: ESPHome Device Builder, preloaded with the `blueos-relay` factory
# project (Waveshare ESP32-S3-Relay-6CH + Pico-RTC-DS3231).
#
# Base: official esphome/esphome image (bundles the ESPHome CLI, PlatformIO/esp-idf
# toolchains, and the modern Device Builder dashboard). Only linux/amd64 + linux/arm64
# are published upstream (arm/v7 support was dropped by the ESPHome project) — this
# matches Pi 4 (64-bit) / Pi 5 BlueOS installs.
#
# PREWARM: during image build we compile blueos-relay once so PlatformIO + ESP-IDF
# land in the image (~/.platformio) and a seed .esphome build cache is copied into
# /config on first start. That turns a 20–40 min first Pi compile into a much shorter
# incremental build / upload. Image gets larger; CI takes longer (especially arm64
# under QEMU). Set PREWARM=0 to skip.
ARG ESPHOME_VERSION=2026.6
FROM esphome/esphome:${ESPHOME_VERSION}

ARG IMAGE_NAME=esphome
ARG AUTHOR="Tony White"
ARG AUTHOR_EMAIL="tony@bluerobotics.com"
ARG MAINTAINER="Tony White"
ARG MAINTAINER_EMAIL="tony@bluerobotics.com"
ARG REPO=vshie/blueos-site-esphome
ARG OWNER=vshie
ARG PREWARM=1

# Wizard needs only the stdlib + PyYAML, which the base image already ships for
# ESPHome's own YAML parsing — no extra pip installs required.
COPY config/blueos-relay.yaml /opt/blueos/factory/blueos-relay.yaml
COPY config/schedule.h /opt/blueos/factory/schedule.h
COPY config/secrets.yaml.example /opt/blueos/factory/secrets.yaml.example
COPY config/secrets.prewarm.yaml /opt/blueos/factory/secrets.prewarm.yaml
COPY www/ /opt/blueos/www/
COPY wizard/wizard.py /opt/blueos/wizard.py
COPY entrypoint.sh /blueos-entrypoint.sh

RUN chmod +x /blueos-entrypoint.sh \
 && mkdir -p /opt/blueos/prewarm

# Compile once in CI so the Pi does not download/build the ESP-IDF toolchain cold.
# Artifacts:
#   /root/.platformio     — stays in the image (not under the /config volume)
#   /opt/blueos/prewarm/esphome — seeded into /config/.esphome on first boot
RUN if [ "$PREWARM" = "1" ]; then \
      set -eux; \
      mkdir -p /tmp/prewarm; \
      cp /opt/blueos/factory/blueos-relay.yaml /tmp/prewarm/; \
      cp /opt/blueos/factory/schedule.h /tmp/prewarm/; \
      cp /opt/blueos/factory/secrets.prewarm.yaml /tmp/prewarm/secrets.yaml; \
      cd /tmp/prewarm; \
      esphome compile blueos-relay.yaml; \
      if [ -d /tmp/prewarm/.esphome ]; then \
        cp -a /tmp/prewarm/.esphome /opt/blueos/prewarm/esphome; \
      fi; \
      # Drop noisy logs / downloads leftovers from the build dir copy, keep objects
      rm -rf /tmp/prewarm; \
      echo "PREWARM ok: platformio=$(du -sh /root/.platformio 2>/dev/null | cut -f1) esphome-cache=$(du -sh /opt/blueos/prewarm/esphome 2>/dev/null | cut -f1)"; \
    else \
      echo "PREWARM skipped"; \
    fi

ENV STATUS_PORT=80 \
    DASHBOARD_PORT=6052 \
    ESPHOME_CONFIG_DIR=/config \
    FACTORY_DIR=/opt/blueos/factory \
    WWW_DIR=/opt/blueos/www \
    BEACON_HOST=host.docker.internal \
    BEACON_PORT=9111 \
    MQTT_TOPIC_PREFIX=blueos/relay \
    PREWARM_ESPHOME_DIR=/opt/blueos/prewarm/esphome

EXPOSE 80/tcp 6052/tcp

VOLUME /config

LABEL version="0.4.2"
LABEL type="other"
LABEL tags='["esphome","mqtt","flash","ota","relay","iot"]'
LABEL requirements="core >= 1.1"

# Privileged + full /dev bind: the ESP32-S3's USB-CDC/JTAG serial node isn't
# knowable ahead of time (varies by hub/board/hotplug order), so we pass the
# whole /dev tree through rather than guessing a fixed device path. OTA
# reflashing (the common path once a device is on the network) needs none of
# this — only first-flash-over-USB does.
LABEL permissions='\
{\
  "ExposedPorts": {\
    "80/tcp": {},\
    "6052/tcp": {}\
  },\
  "HostConfig": {\
    "Privileged": true,\
    "ExtraHosts": ["host.docker.internal:host-gateway"],\
    "PortBindings": {\
      "80/tcp": [{"HostPort": ""}],\
      "6052/tcp": [{"HostPort": "6052"}]\
    },\
    "Binds": [\
      "/usr/blueos/extensions/esphome:/config",\
      "/dev:/dev"\
    ]\
  }\
}'

LABEL authors='[{"name": "Tony White", "email": "tony@bluerobotics.com"}]'
LABEL company='{\
  "about": "ESPHome Device Builder for BlueOS, preloaded with the blueos-relay project and Beacon-injected MQTT broker",\
  "name": "Community",\
  "email": "tony@bluerobotics.com"\
}'
LABEL readme="https://raw.githubusercontent.com/${REPO}/{tag}/README.md"
LABEL links='{\
  "source": "https://github.com/vshie/blueos-site-esphome",\
  "documentation": "https://github.com/vshie/blueos-site-esphome/blob/main/README.md"\
}'

LABEL org.blueos.image-name="${IMAGE_NAME}"
LABEL org.blueos.authors="[{\"name\": \"${AUTHOR}\", \"email\": \"${AUTHOR_EMAIL}\"}]"
LABEL org.blueos.company="{\"about\": \"ESPHome Device Builder for BlueOS\", \"name\": \"${MAINTAINER}\", \"email\": \"${MAINTAINER_EMAIL}\"}"

ENTRYPOINT ["/blueos-entrypoint.sh"]
