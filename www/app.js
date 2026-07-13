const el = (id) => document.getElementById(id);

let lastStatus = null;

function setStatusLine(node, text, cls) {
  node.textContent = text;
  node.className = "status-line" + (cls ? ` ${cls}` : "");
}

function dashboardUrl(port) {
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}

function populateBeacon(status) {
  const { beacon } = status;
  const line = el("beacon-status");
  const select = el("broker-select");
  select.innerHTML = "";

  const candidates = (beacon.candidates || []).slice();
  if (status.current.mqtt_broker && !candidates.includes(status.current.mqtt_broker)) {
    candidates.unshift(status.current.mqtt_broker);
  }
  if (candidates.length === 0) {
    candidates.push("blueos.local");
  }
  for (const c of candidates) {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    select.appendChild(opt);
  }
  if (status.current.mqtt_broker) {
    select.value = status.current.mqtt_broker;
  }

  if (beacon.available) {
    setStatusLine(
      line,
      `Beacon reports hostname "${beacon.hostname}" → suggested broker "${beacon.candidates[0]}"`,
      "ok"
    );
  } else {
    setStatusLine(
      line,
      `Could not reach Beacon at ${beacon.source} (${beacon.error || "unknown error"}). ` +
        `Enter the broker manually (e.g. a static IP) below.`,
      "warn"
    );
  }
}

function populateSecrets(status) {
  const { current } = status;
  const line = el("secrets-status");
  const parts = [];
  parts.push(current.api_encryption_key_set ? "API key: set" : "API key: will be generated");
  parts.push(current.ota_password_set ? "OTA password: set" : "OTA password: will be generated");
  setStatusLine(line, parts.join(" · "), current.api_encryption_key_set && current.ota_password_set ? "ok" : "warn");

  el("wifi-ssid").value = current.wifi_ssid || "";
  el("wifi-password").placeholder = current.wifi_password_set
    ? "Already set — leave blank to keep it"
    : "Site Wi‑Fi password";
}

function populateUsb(status) {
  const { usb } = status;
  const line = el("usb-status");
  const found = [...(usb.by_id || []), ...(usb.ports || [])];
  if (found.length > 0) {
    setStatusLine(line, `Serial device(s) detected: ${found.join(", ")}`, "ok");
  } else {
    setStatusLine(
      line,
      "No USB serial device detected. Plug the ESP32 into a USB port on the BlueOS Pi for first flash, or use OTA if it's already on the network.",
      "warn"
    );
  }
}

async function loadStatus() {
  const res = await fetch("/api/status");
  const status = await res.json();
  lastStatus = status;
  populateBeacon(status);
  populateSecrets(status);
  populateUsb(status);
  el("topic-prefix").textContent = status.topic_prefix;
  el("config-dir").textContent = status.config_dir;
  el("open-dashboard").onclick = () => window.open(dashboardUrl(status.dashboard_port), "_blank");
  return status;
}

async function save() {
  const result = el("save-result");
  const broker = el("broker-custom").value.trim() || el("broker-select").value.trim();
  const payload = {
    wifi_ssid: el("wifi-ssid").value.trim(),
    wifi_password: el("wifi-password").value,
    mqtt_broker: broker,
    regen_api_key: el("regen-api").checked,
    regen_ota_password: el("regen-ota").checked,
  };
  setStatusLine(result, "Saving…", "");
  try {
    const res = await fetch("/api/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      setStatusLine(result, `Failed: ${data.error || res.statusText}`, "err");
      return;
    }
    setStatusLine(
      result,
      `Saved. Broker=${data.mqtt_broker || "(unset)"} · secrets.yaml + blueos-relay.yaml ready in ${data.yaml_path}`,
      "ok"
    );
    el("wifi-password").value = "";
    el("regen-api").checked = false;
    el("regen-ota").checked = false;
    await loadStatus();
  } catch (err) {
    setStatusLine(result, `Failed: ${err}`, "err");
  }
}

el("refresh-beacon").addEventListener("click", loadStatus);
el("refresh-usb").addEventListener("click", loadStatus);
el("save-btn").addEventListener("click", save);

loadStatus();
