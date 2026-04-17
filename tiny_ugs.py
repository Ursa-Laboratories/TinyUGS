#!/usr/bin/env python3
"""Tiny GRBL browser panel designed for SSH port forwarding.

Run this on the remote host:

    python tiny_ugs.py --serial-port /dev/ttyUSB0 --web-port 8765 --auto-connect

From your local machine, forward the port:

    ssh -L 8765:127.0.0.1:8765 <user>@<host>

Then open:

    http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:
    import serial
    from serial.tools import list_ports
except Exception as exc:  # pragma: no cover - import guard for remote hosts
    raise SystemExit(
        "tiny_ugs requires the 'pyserial' package, not the unrelated 'serial' package.\n"
        "Fix the environment with:\n"
        "  pip uninstall -y serial\n"
        "  pip install -r requirements.txt\n"
        f"Original import error: {exc}"
    ) from exc


WPOS_PATTERN = re.compile(r"WPos:([\d.-]+),([\d.-]+),([\d.-]+)")
MPOS_PATTERN = re.compile(r"MPos:([\d.-]+),([\d.-]+),([\d.-]+)")
WCO_PATTERN = re.compile(r"WCO:([\d.-]+),([\d.-]+),([\d.-]+)")


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tiny UGS</title>
  <style>
    body {
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: #10161d;
      color: #e9f0f7;
    }
    .wrap {
      max-width: 1100px;
      margin: 0 auto;
      padding: 18px;
    }
    .hero, .panel {
      background: #18222d;
      border: 1px solid #2d445a;
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 14px;
    }
    .hero h1, .panel h2 {
      margin: 0 0 10px;
    }
    .hero p, .muted {
      color: #a7bbce;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
    }
    .row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 10px;
    }
    label {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 110px;
      font-size: 12px;
      color: #a7bbce;
      flex: 1;
    }
    input, button {
      font: inherit;
      border-radius: 10px;
      border: 1px solid #37526b;
      background: #0d141b;
      color: #e9f0f7;
      padding: 10px 12px;
    }
    button {
      background: #213243;
      cursor: pointer;
    }
    button:hover {
      background: #2a4157;
    }
    button.primary { background: #1e4b43; }
    button.warn { background: #5a4816; }
    button.danger { background: #5b1f30; }
    .stats, .coords {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }
    .card {
      background: #0d141b;
      border: 1px solid #2d445a;
      border-radius: 12px;
      padding: 10px;
    }
    .card .label {
      color: #a7bbce;
      font-size: 11px;
      margin-bottom: 6px;
      text-transform: uppercase;
    }
    .card .value {
      font-size: 18px;
    }
    .status {
      background: #0d141b;
      border: 1px solid #2d445a;
      border-radius: 12px;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
      color: #c3d4e5;
    }
    .jog {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .jog button {
      min-height: 46px;
    }
    .hidden {
      visibility: hidden;
    }
    pre {
      margin: 0;
      min-height: 160px;
      max-height: 300px;
      overflow: auto;
      padding: 12px;
      border-radius: 12px;
      background: #0d141b;
      border: 1px solid #2d445a;
      color: #d6ffe6;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .settings-tools {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .settings-list {
      display: grid;
      gap: 8px;
      margin-top: 12px;
      max-height: 280px;
      overflow: auto;
      padding-right: 4px;
    }
    .setting-row {
      display: grid;
      grid-template-columns: 100px minmax(0, 1fr) 84px;
      gap: 8px;
      align-items: center;
      background: #0d141b;
      border: 1px solid #2d445a;
      border-radius: 12px;
      padding: 8px;
    }
    .setting-key {
      color: #c3d4e5;
      font-size: 13px;
    }
    .setting-empty {
      color: #a7bbce;
      font-size: 12px;
      padding: 10px;
      background: #0d141b;
      border: 1px solid #2d445a;
      border-radius: 12px;
    }
    .pill {
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid #37526b;
      background: #213243;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Tiny UGS</h1>
      <p>Minimal GRBL panel for SSH-tunneled remote use. Raw controller-space only: the values and moves here are plain GRBL <code>WPos</code>/<code>MPos</code>, not CubOS-translated coordinates.</p>
      <div class="pill" id="connection-pill">Disconnected</div>
    </section>

    <div class="grid">
      <section class="panel">
        <h2>Connection</h2>
        <div class="row">
          <label>Serial Port
            <input id="serial-port" list="port-options" placeholder="/dev/ttyUSB0">
            <datalist id="port-options"></datalist>
          </label>
          <label>Baudrate
            <input id="baudrate" type="number" value="115200">
          </label>
          <label>Timeout (s)
            <input id="timeout" type="number" value="1.0" step="0.1">
          </label>
        </div>
        <div class="row">
          <button class="primary" id="connect-btn">Connect</button>
          <button id="disconnect-btn">Disconnect</button>
          <button id="refresh-state-btn">Refresh</button>
          <span class="muted" id="connection-summary">No active serial connection.</span>
        </div>

        <div class="stats">
          <div class="card"><div class="label">State</div><div class="value" id="state-value">Unknown</div></div>
          <div class="card"><div class="label">Report Mode</div><div class="value" id="report-mode-value">Unknown</div></div>
          <div class="card"><div class="label">WCO</div><div class="value" id="wco-value">--</div></div>
        </div>

        <div class="coords">
          <div class="card"><div class="label">WPos X</div><div class="value" id="wpos-x">--</div></div>
          <div class="card"><div class="label">WPos Y</div><div class="value" id="wpos-y">--</div></div>
          <div class="card"><div class="label">WPos Z</div><div class="value" id="wpos-z">--</div></div>
        </div>

        <div class="coords">
          <div class="card"><div class="label">MPos X</div><div class="value" id="mpos-x">--</div></div>
          <div class="card"><div class="label">MPos Y</div><div class="value" id="mpos-y">--</div></div>
          <div class="card"><div class="label">MPos Z</div><div class="value" id="mpos-z">--</div></div>
        </div>

        <div class="status" id="raw-status">No status yet.</div>
      </section>

      <section class="panel">
        <h2>Motion</h2>
        <div class="row">
          <button class="primary" id="home-btn">Home</button>
          <button id="unlock-btn">Unlock</button>
          <button class="warn" id="reset-unlock-btn">Reset + Unlock</button>
          <button class="danger" id="stop-btn">Feed Hold</button>
          <button id="resume-btn">Resume</button>
        </div>

        <div class="row">
          <label>Step (mm)
            <input id="jog-step" type="number" value="1.0" step="0.1">
          </label>
          <label>Jog Feed
            <input id="jog-feed" type="number" value="1200" step="100">
          </label>
        </div>
        <div class="jog">
          <div class="hidden"></div>
          <button data-jog="0,1,0">Y+</button>
          <div class="hidden"></div>
          <button data-jog="-1,0,0">X-</button>
          <button data-jog="0,0,1">Z+</button>
          <button data-jog="1,0,0">X+</button>
          <div class="hidden"></div>
          <button data-jog="0,-1,0">Y-</button>
          <div class="hidden"></div>
          <button data-jog="0,0,-1">Z-</button>
          <button class="danger" id="jog-cancel-btn">Cancel Jog</button>
          <div class="hidden"></div>
        </div>

        <div class="row" style="margin-top: 12px;">
          <label>X
            <input id="move-x" type="number" step="0.1" placeholder="leave blank to keep">
          </label>
          <label>Y
            <input id="move-y" type="number" step="0.1" placeholder="leave blank to keep">
          </label>
          <label>Z
            <input id="move-z" type="number" step="0.1" placeholder="leave blank to keep">
          </label>
          <label>Move Feed
            <input id="move-feed" type="number" value="2000" step="100">
          </label>
        </div>
        <div class="row">
          <button class="primary" id="move-btn">Send Absolute Move</button>
        </div>
      </section>

      <section class="panel">
        <h2>Settings</h2>
        <div class="row">
          <button class="primary" id="settings-btn">Read $$</button>
        </div>
        <div class="settings-tools">
          <label>Setting
            <input id="setting-key" type="text" placeholder="$10">
          </label>
          <label>Value
            <input id="setting-value" type="text" placeholder="0">
          </label>
        </div>
        <div class="row">
          <button id="set-setting-btn">Apply Setting</button>
          <button id="set-wpos-btn">Set $10=0 (WPos)</button>
          <button id="set-mpos-btn">Set $10=1 (MPos)</button>
        </div>
        <pre id="settings-view">No settings loaded yet.</pre>
        <div class="settings-list" id="settings-editor">
          <div class="setting-empty">Read settings to load editable rows.</div>
        </div>
      </section>

      <section class="panel">
        <h2>Activity</h2>
        <pre id="activity-log">Panel ready.</pre>
      </section>
    </div>
  </div>

  <script>
    const el = {
      portInput: document.getElementById("serial-port"),
      portOptions: document.getElementById("port-options"),
      baudrate: document.getElementById("baudrate"),
      timeout: document.getElementById("timeout"),
      connectionPill: document.getElementById("connection-pill"),
      connectionSummary: document.getElementById("connection-summary"),
      stateValue: document.getElementById("state-value"),
      reportModeValue: document.getElementById("report-mode-value"),
      wcoValue: document.getElementById("wco-value"),
      rawStatus: document.getElementById("raw-status"),
      settingsView: document.getElementById("settings-view"),
      settingsEditor: document.getElementById("settings-editor"),
      settingKey: document.getElementById("setting-key"),
      settingValue: document.getElementById("setting-value"),
      activityLog: document.getElementById("activity-log"),
      wposX: document.getElementById("wpos-x"),
      wposY: document.getElementById("wpos-y"),
      wposZ: document.getElementById("wpos-z"),
      mposX: document.getElementById("mpos-x"),
      mposY: document.getElementById("mpos-y"),
      mposZ: document.getElementById("mpos-z"),
    };

    function fmt(value) {
      if (value === null || value === undefined || Number.isNaN(value)) return "--";
      return Number(value).toFixed(3);
    }

    function fmtVec(vec) {
      return vec ? `${fmt(vec.x)}, ${fmt(vec.y)}, ${fmt(vec.z)}` : "--";
    }

    function log(message) {
      const stamp = new Date().toLocaleTimeString();
      const next = `[${stamp}] ${message}`;
      const prev = el.activityLog.textContent.trim();
      el.activityLog.textContent = prev ? `${next}\n${prev}` : next;
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      return data;
    }

    function renderPorts(ports) {
      el.portOptions.innerHTML = "";
      for (const port of ports || []) {
        const option = document.createElement("option");
        option.value = port.device;
        option.label = `${port.device}${port.description ? ` - ${port.description}` : ""}`;
        el.portOptions.appendChild(option);
      }
    }

    function renderState(data) {
      const connected = Boolean(data.connected);
      el.connectionPill.textContent = connected ? `Connected: ${data.serial_port}` : "Disconnected";
      el.connectionSummary.textContent = connected
        ? `Serial: ${data.serial_port} @ ${data.baudrate} baud`
        : "No active serial connection.";

      const status = data.status || {};
      const wpos = status.wpos || {};
      const mpos = status.mpos || {};
      el.stateValue.textContent = status.state || "Unknown";
      el.reportModeValue.textContent = data.report_mode || "Unknown";
      el.wcoValue.textContent = fmtVec(status.wco);
      el.rawStatus.textContent = data.raw_status || "No status yet.";
      el.wposX.textContent = fmt(wpos.x);
      el.wposY.textContent = fmt(wpos.y);
      el.wposZ.textContent = fmt(wpos.z);
      el.mposX.textContent = fmt(mpos.x);
      el.mposY.textContent = fmt(mpos.y);
      el.mposZ.textContent = fmt(mpos.z);

      if (!el.portInput.value && data.available_ports && data.available_ports.length) {
        el.portInput.value = data.serial_port || data.available_ports[0].device;
      }
      renderPorts(data.available_ports);

      if (data.settings) {
        renderSettingsEditor(data.settings);
      }
    }

    function renderSettingsEditor(settings) {
      const entries = Object.entries(settings || {}).sort((left, right) => {
        return Number(left[0].slice(1)) - Number(right[0].slice(1));
      });
      el.settingsEditor.innerHTML = "";

      if (!entries.length) {
        const empty = document.createElement("div");
        empty.className = "setting-empty";
        empty.textContent = "Read settings to load editable rows.";
        el.settingsEditor.appendChild(empty);
        return;
      }

      for (const [key, value] of entries) {
        const row = document.createElement("div");
        row.className = "setting-row";

        const keyCell = document.createElement("div");
        keyCell.className = "setting-key";
        keyCell.textContent = key;

        const input = document.createElement("input");
        input.type = "text";
        input.value = value;
        input.dataset.settingKey = key;

        const button = document.createElement("button");
        button.textContent = "Apply";
        button.addEventListener("click", () => {
          setSetting(key, input.value).catch(error => log(error.message));
        });

        row.appendChild(keyCell);
        row.appendChild(input);
        row.appendChild(button);
        el.settingsEditor.appendChild(row);
      }
    }

    async function refreshState() {
      try {
        renderState(await api("/api/state"));
      } catch (error) {
        log(`State refresh failed: ${error.message}`);
      }
    }

    async function refreshSettings() {
      try {
        const data = await api("/api/settings");
        el.settingsView.textContent = data.settings_raw || "<no settings returned>";
        if (data.snapshot) renderState(data.snapshot);
        log("Read GRBL settings.");
      } catch (error) {
        log(`Settings read failed: ${error.message}`);
      }
    }

    async function setSetting(key, value) {
      const trimmedKey = String(key || "").trim();
      const trimmedValue = String(value || "").trim();
      if (!trimmedKey) {
        log("Enter a GRBL setting key like $10.");
        return;
      }
      if (trimmedValue === "") {
        log("Enter a GRBL setting value.");
        return;
      }
      const data = await api("/api/set-setting", {
        method: "POST",
        body: JSON.stringify({ key: trimmedKey, value: trimmedValue }),
      });
      if (data.snapshot) renderState(data.snapshot);
      if (data.settings_raw) {
        el.settingsView.textContent = data.settings_raw;
      }
      el.settingKey.value = trimmedKey;
      el.settingValue.value = trimmedValue;
      log(`Applied ${trimmedKey}=${trimmedValue}`);
      if (data.response) log(data.response.trim());
    }

    async function post(path, body, successText) {
      const data = await api(path, {
        method: "POST",
        body: JSON.stringify(body || {}),
      });
      if (data.snapshot) renderState(data.snapshot);
      if (data.response) log(data.response.trim());
      if (successText) log(successText);
    }

    function num(id) {
      const raw = document.getElementById(id).value;
      return raw === "" ? null : Number(raw);
    }

    async function connect() {
      const body = {
        serial_port: el.portInput.value.trim(),
        baudrate: Number(el.baudrate.value),
        timeout: Number(el.timeout.value),
      };
      if (!body.serial_port) {
        log("Enter a serial port first.");
        return;
      }
      await post("/api/connect", body, `Connected to ${body.serial_port}.`);
      await refreshSettings();
    }

    async function jog(dx, dy, dz) {
      const step = Number(document.getElementById("jog-step").value);
      const feed = Number(document.getElementById("jog-feed").value);
      await post("/api/jog", {
        x: dx * step,
        y: dy * step,
        z: dz * step,
        feed_rate: feed,
      }, `Jogged X:${dx * step} Y:${dy * step} Z:${dz * step}`);
    }

    async function moveAbs() {
      const body = {
        x: num("move-x"),
        y: num("move-y"),
        z: num("move-z"),
        feed_rate: Number(document.getElementById("move-feed").value),
      };
      if (body.x === null && body.y === null && body.z === null) {
        log("Enter at least one axis value.");
        return;
      }
      await post("/api/move", body, `Sent absolute move to X:${body.x} Y:${body.y} Z:${body.z}`);
    }

    document.getElementById("connect-btn").addEventListener("click", () => connect().catch(e => log(e.message)));
    document.getElementById("disconnect-btn").addEventListener("click", () => post("/api/disconnect", {}, "Disconnected.").catch(e => log(e.message)));
    document.getElementById("refresh-state-btn").addEventListener("click", refreshState);
    document.getElementById("settings-btn").addEventListener("click", refreshSettings);
    document.getElementById("set-setting-btn").addEventListener("click", () => setSetting(el.settingKey.value, el.settingValue.value).catch(e => log(e.message)));
    document.getElementById("set-wpos-btn").addEventListener("click", () => setSetting("$10", "0").catch(e => log(e.message)));
    document.getElementById("set-mpos-btn").addEventListener("click", () => setSetting("$10", "1").catch(e => log(e.message)));
    document.getElementById("home-btn").addEventListener("click", () => post("/api/home", {}, "Sent home command.").catch(e => log(e.message)));
    document.getElementById("unlock-btn").addEventListener("click", () => post("/api/unlock", {}, "Sent unlock command.").catch(e => log(e.message)));
    document.getElementById("reset-unlock-btn").addEventListener("click", () => post("/api/reset-unlock", {}, "Sent reset + unlock.").catch(e => log(e.message)));
    document.getElementById("stop-btn").addEventListener("click", () => post("/api/stop", {}, "Sent feed hold.").catch(e => log(e.message)));
    document.getElementById("resume-btn").addEventListener("click", () => post("/api/resume", {}, "Sent resume.").catch(e => log(e.message)));
    document.getElementById("jog-cancel-btn").addEventListener("click", () => post("/api/jog-cancel", {}, "Sent jog cancel.").catch(e => log(e.message)));
    document.getElementById("move-btn").addEventListener("click", () => moveAbs().catch(e => log(e.message)));

    document.querySelectorAll("[data-jog]").forEach(button => {
      button.addEventListener("click", () => {
        const [dx, dy, dz] = button.dataset.jog.split(",").map(Number);
        jog(dx, dy, dz).catch(e => log(e.message));
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.target && event.target.tagName === "INPUT") return;
      if (event.repeat) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); jog(-1, 0, 0).catch(e => log(e.message)); }
      if (event.key === "ArrowRight") { event.preventDefault(); jog(1, 0, 0).catch(e => log(e.message)); }
      if (event.key === "ArrowUp") { event.preventDefault(); jog(0, 1, 0).catch(e => log(e.message)); }
      if (event.key === "ArrowDown") { event.preventDefault(); jog(0, -1, 0).catch(e => log(e.message)); }
      if (event.key === "PageUp") { event.preventDefault(); jog(0, 0, 1).catch(e => log(e.message)); }
      if (event.key === "PageDown") { event.preventDefault(); jog(0, 0, -1).catch(e => log(e.message)); }
    });

    refreshState();
    window.setInterval(refreshState, 1000);
  </script>
</body>
</html>
"""


@dataclass
class SerialPortInfo:
    device: str
    description: str


def parse_triplet(pattern: re.Pattern[str], text: str) -> tuple[float, float, float] | None:
    match = pattern.search(text)
    if not match:
        return None
    return tuple(float(match.group(i)) for i in range(1, 4))


def to_xyz(values: tuple[float, float, float] | None) -> dict[str, float] | None:
    if values is None:
        return None
    return {"x": values[0], "y": values[1], "z": values[2]}


def add_triplets(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(x + y for x, y in zip(a, b))


def subtract_triplets(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(x - y for x, y in zip(a, b))


def parse_status(raw_status: str) -> dict[str, Any]:
    text = raw_status.strip()
    if not text:
        return {"state": None, "reported_frame": None, "wpos": None, "mpos": None, "wco": None}

    stripped = text.strip("<>")
    parts = stripped.split("|")
    state = parts[0] if parts else None

    wpos = parse_triplet(WPOS_PATTERN, text)
    mpos = parse_triplet(MPOS_PATTERN, text)
    wco = parse_triplet(WCO_PATTERN, text)

    if wpos is None and mpos is not None and wco is not None:
        wpos = subtract_triplets(mpos, wco)
    if mpos is None and wpos is not None and wco is not None:
        mpos = add_triplets(wpos, wco)

    reported_frame = None
    if "WPos:" in text:
        reported_frame = "WPos"
    elif "MPos:" in text:
        reported_frame = "MPos"

    return {
        "state": state,
        "reported_frame": reported_frame,
        "wpos": to_xyz(wpos),
        "mpos": to_xyz(mpos),
        "wco": to_xyz(wco),
    }


def parse_settings(raw_settings: str) -> dict[str, str]:
    settings: dict[str, str] = {}
    for line in raw_settings.splitlines():
        if line.startswith("$") and "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
    return settings


def validate_setting_key(key: str) -> str:
    cleaned = key.strip()
    if not re.fullmatch(r"\$\d+", cleaned):
        raise RuntimeError("GRBL setting keys must look like $10 or $132")
    return cleaned


class GRBLSession:
    def __init__(self, serial_port: str | None, baudrate: int, timeout: float) -> None:
        self._lock = threading.Lock()
        self._serial: serial.Serial | None = None
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.last_status = ""
        self.last_settings = ""

    def list_ports(self) -> list[SerialPortInfo]:
        return [
            SerialPortInfo(device=port.device, description=port.description or "")
            for port in sorted(list_ports.comports(), key=lambda item: item.device)
        ]

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _drain_unlocked(self, pause: float = 0.2) -> str:
        assert self._serial is not None
        time.sleep(pause)
        chunks: list[bytes] = []
        while True:
            waiting = self._serial.in_waiting
            if waiting <= 0:
                break
            chunks.append(self._serial.read(waiting))
            time.sleep(0.05)
        return b"".join(chunks).decode("ascii", errors="replace")

    def _ensure_connected_unlocked(self) -> serial.Serial:
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("Serial connection is not open")
        return self._serial

    def _write_and_read_unlocked(self, command: bytes, pause: float = 0.2) -> str:
        ser = self._ensure_connected_unlocked()
        ser.write(command)
        ser.flush()
        return self._drain_unlocked(pause=pause)

    def connect(self, serial_port: str | None, baudrate: int | None, timeout: float | None) -> dict[str, Any]:
        port = serial_port or self.serial_port
        if not port:
            raise RuntimeError("No serial port provided")

        with self._lock:
            self.disconnect_unlocked()
            self.serial_port = port
            self.baudrate = int(baudrate or self.baudrate)
            self.timeout = float(timeout or self.timeout)
            try:
                self._serial = serial.Serial(
                    port=self.serial_port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                )
                time.sleep(2.0)
                self._drain_unlocked(pause=0.1)
                self._write_and_read_unlocked(b"\r\n", pause=0.15)
                self.last_status = self._write_and_read_unlocked(b"?", pause=0.15).strip()
            except Exception:
                if self._serial is not None:
                    try:
                        self._serial.close()
                    except Exception:
                        pass
                self._serial = None
                raise
        return self.snapshot(refresh_status=False)

    def disconnect_unlocked(self) -> None:
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self.disconnect_unlocked()
            self.last_status = ""
        return self.snapshot(refresh_status=False)

    def query_status(self) -> str:
        with self._lock:
            if not self.is_connected():
                self.last_status = ""
                return self.last_status
            self.last_status = self._write_and_read_unlocked(b"?", pause=0.15).strip()
            return self.last_status

    def read_settings(self) -> str:
        with self._lock:
            self.last_settings = self._write_and_read_unlocked(b"$$\n", pause=0.5).strip()
            return self.last_settings

    def set_setting(self, key: str, value: str) -> tuple[str, str]:
        setting_key = validate_setting_key(key)
        setting_value = value.strip()
        if setting_value == "":
            raise RuntimeError("GRBL setting value cannot be empty")
        if "\n" in setting_value or "\r" in setting_value:
            raise RuntimeError("GRBL setting value cannot contain newlines")

        with self._lock:
            response = self._write_and_read_unlocked(
                f"{setting_key}={setting_value}\n".encode("ascii"),
                pause=0.25,
            ).strip()
            self.last_settings = self._write_and_read_unlocked(b"$$\n", pause=0.5).strip()
            return response, self.last_settings

    def unlock(self) -> str:
        with self._lock:
            return self._write_and_read_unlocked(b"$X\n", pause=0.3).strip()

    def home(self) -> str:
        with self._lock:
            return self._write_and_read_unlocked(b"$H\n", pause=0.3).strip()

    def reset_unlock(self) -> str:
        with self._lock:
            reset_response = self._write_and_read_unlocked(b"\x18", pause=0.8).strip()
            unlock_response = self._write_and_read_unlocked(b"$X\n", pause=0.3).strip()
            return "\n".join(part for part in [reset_response, unlock_response] if part).strip()

    def feed_hold(self) -> str:
        with self._lock:
            return self._write_and_read_unlocked(b"!", pause=0.1).strip()

    def resume(self) -> str:
        with self._lock:
            return self._write_and_read_unlocked(b"~", pause=0.1).strip()

    def jog_cancel(self) -> str:
        with self._lock:
            return self._write_and_read_unlocked(b"\x85", pause=0.1).strip()

    def jog(self, x: float, y: float, z: float, feed_rate: float) -> str:
        if x == 0 and y == 0 and z == 0:
            raise RuntimeError("Jog request must move at least one axis")
        command = f"$J=G21 G91 X{x:.3f} Y{y:.3f} Z{z:.3f} F{feed_rate:.1f}\n".encode("ascii")
        with self._lock:
            return self._write_and_read_unlocked(command, pause=0.1).strip()

    def move_absolute(self, x: float | None, y: float | None, z: float | None, feed_rate: float) -> str:
        if x is None and y is None and z is None:
            raise RuntimeError("Absolute move must include at least one axis")
        axes: list[str] = []
        if x is not None:
            axes.append(f"X{x:.3f}")
        if y is not None:
            axes.append(f"Y{y:.3f}")
        if z is not None:
            axes.append(f"Z{z:.3f}")
        with self._lock:
            responses = [
                self._write_and_read_unlocked(b"G21\n", pause=0.05).strip(),
                self._write_and_read_unlocked(b"G90\n", pause=0.05).strip(),
                self._write_and_read_unlocked(f"G1 {' '.join(axes)} F{feed_rate:.1f}\n".encode("ascii"), pause=0.1).strip(),
            ]
            return "\n".join(part for part in responses if part).strip()

    def snapshot(self, refresh_status: bool) -> dict[str, Any]:
        if refresh_status and self.is_connected():
            try:
                self.query_status()
            except Exception as exc:
                self.last_status = f"<StatusError|{exc}>"
        status = parse_status(self.last_status)
        settings = parse_settings(self.last_settings)
        report_mode = {"0": "WPos", "1": "MPos"}.get(settings.get("$10"), status.get("reported_frame"))
        return {
            "ok": True,
            "connected": self.is_connected(),
            "serial_port": self.serial_port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
            "available_ports": [port.__dict__ for port in self.list_ports()],
            "raw_status": self.last_status,
            "status": status,
            "settings_raw": self.last_settings,
            "settings": settings,
            "report_mode": report_mode,
        }


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "TinyUGS/0.1"

    @property
    def session(self) -> GRBLSession:
        return self.server.session  # type: ignore[attr-defined]

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send_html()
            return
        if self.path == "/api/state":
            self._send_json(self.session.snapshot(refresh_status=True))
            return
        if self.path == "/api/settings":
            try:
                settings_raw = self.session.read_settings()
                self._send_json({
                    "ok": True,
                    "settings_raw": settings_raw,
                    "settings": parse_settings(settings_raw),
                    "snapshot": self.session.snapshot(refresh_status=True),
                })
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_json()
            if self.path == "/api/connect":
                snapshot = self.session.connect(
                    serial_port=body.get("serial_port"),
                    baudrate=body.get("baudrate"),
                    timeout=body.get("timeout"),
                )
                self._send_json(snapshot)
                return
            if self.path == "/api/disconnect":
                self._send_json(self.session.disconnect())
                return
            if self.path == "/api/set-setting":
                response, settings_raw = self.session.set_setting(
                    key=str(body.get("key", "")),
                    value=str(body.get("value", "")),
                )
                self._send_json({
                    "ok": True,
                    "response": response,
                    "settings_raw": settings_raw,
                    "settings": parse_settings(settings_raw),
                    "snapshot": self.session.snapshot(refresh_status=True),
                })
                return
            if self.path == "/api/home":
                response = self.session.home()
            elif self.path == "/api/unlock":
                response = self.session.unlock()
            elif self.path == "/api/reset-unlock":
                response = self.session.reset_unlock()
            elif self.path == "/api/stop":
                response = self.session.feed_hold()
            elif self.path == "/api/resume":
                response = self.session.resume()
            elif self.path == "/api/jog-cancel":
                response = self.session.jog_cancel()
            elif self.path == "/api/jog":
                response = self.session.jog(
                    x=float(body.get("x", 0.0)),
                    y=float(body.get("y", 0.0)),
                    z=float(body.get("z", 0.0)),
                    feed_rate=float(body.get("feed_rate", 1200.0)),
                )
            elif self.path == "/api/move":
                response = self.session.move_absolute(
                    x=None if body.get("x") is None else float(body.get("x")),
                    y=None if body.get("y") is None else float(body.get("y")),
                    z=None if body.get("z") is None else float(body.get("z")),
                    feed_rate=float(body.get("feed_rate", 2000.0)),
                )
            else:
                self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            self._send_json({
                "ok": True,
                "response": response,
                "snapshot": self.session.snapshot(refresh_status=True),
            })
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--serial-port", help="Serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=115200, help="GRBL baudrate")
    parser.add_argument("--timeout", type=float, default=1.0, help="Serial timeout in seconds")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--web-port", type=int, default=8765, help="HTTP bind port")
    parser.add_argument("--auto-connect", action="store_true", help="Connect on startup")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = GRBLSession(args.serial_port, args.baudrate, args.timeout)
    if args.auto_connect:
        session.connect(args.serial_port, args.baudrate, args.timeout)

    try:
        server = ThreadingHTTPServer((args.host, args.web_port), RequestHandler)
    except OSError as exc:
        print(f"Failed to bind http://{args.host}:{args.web_port}: {exc}")
        return 1

    server.session = session  # type: ignore[attr-defined]
    print(f"Tiny UGS listening on http://{args.host}:{args.web_port}")
    print("Use ssh -L to forward this port to your local machine.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nShutting down...")
    finally:
        server.server_close()
        session.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
