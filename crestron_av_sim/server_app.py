from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import os
import socket
import threading
import webbrowser
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

APP_NAME = "Crestron AV Lab Simulator"
DEFAULT_CATALOG = "catalog/device_catalog.json"
DEFAULT_SCENARIOS = "config/scenarios.json"
DEFAULT_LAB = "config/labs/default_lab.json"


def load_json(path: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return fallback or {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(path: str, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def parse_value(raw: str) -> Any:
    text = raw.strip()
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in {"null", "none"}:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def crestron_bool(v: Any) -> str:
    return "true" if v is True else "false" if v is False else str(v)


def esc(value: Any) -> str:
    return html_lib.escape(str(value))


def local_ip_hint() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


class CommandLog:
    def __init__(self, path: str = "logs/commands.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(exist_ok=True)
        self.recent: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def add(self, device_id: str, direction: str, payload: Any, peer: str = "") -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "device": device_id,
            "dir": direction,
            "peer": peer,
            "payload": payload if isinstance(payload, str) else repr(payload),
        }
        with self.lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self.recent = (self.recent + [entry])[-500:]
        print(f"{entry['ts']} {device_id} {direction} {entry['payload']}")


class Device:
    def __init__(self, cfg: dict[str, Any], defaults: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> None:
        model_key = cfg.get("model_key", cfg.get("model", cfg.get("type", "generic_display_tcp")))
        model = catalog.get(model_key, {})
        self.id = str(cfg["id"])
        self.name = str(cfg.get("name", self.id))
        self.model_key = model_key
        self.vendor = str(cfg.get("vendor", model.get("vendor", "Generic")))
        self.model = str(cfg.get("model", model.get("model", model_key)))
        self.family = str(cfg.get("family", model.get("family", "Generic")))
        self.type = str(cfg.get("type", model.get("type", "display")))
        self.protocol = str(cfg.get("protocol", model.get("protocol", self.default_protocol(self.type))))
        self.host = str(cfg.get("host", defaults.get("host", "0.0.0.0")))
        self.port = int(cfg.get("port", model.get("default_port", 0)))
        state = deepcopy(model.get("default_state", {}))
        state.update(deepcopy(cfg.get("state", {})))
        self.state = {
            "online": cfg.get("online", defaults.get("online", True)),
            "response_delay_ms": cfg.get("response_delay_ms", defaults.get("response_delay_ms", 0)),
            **state,
        }
        self.rules = deepcopy(model.get("response_rules", [])) + deepcopy(cfg.get("response_rules", []))

    @staticmethod
    def default_protocol(kind: str) -> str:
        return {"nvx_http": "http", "visca_udp_camera": "udp"}.get(kind, "tcp")

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.state[key] = value

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "vendor": self.vendor,
            "model": self.model,
            "model_key": self.model_key,
            "family": self.family,
            "type": self.type,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "state": deepcopy(self.state),
        }

    def to_lab_config(self) -> dict[str, Any]:
        state = deepcopy(self.state)
        online = state.pop("online", True)
        response_delay_ms = state.pop("response_delay_ms", 0)
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "model_key": self.model_key,
            "host": self.host,
            "port": self.port,
            "online": online,
            "response_delay_ms": response_delay_ms,
            "state": state,
        }
        return data


class LabApp:
    def __init__(self, lab_path: str, lab: dict[str, Any], catalog_doc: dict[str, Any], scenarios_doc: dict[str, Any]) -> None:
        self.lab_path = lab_path
        self.lab = lab
        self.catalog_doc = catalog_doc
        self.catalog = {m["key"]: m for m in catalog_doc.get("models", [])}
        defaults = lab.get("defaults", {"host": "0.0.0.0", "online": True, "response_delay_ms": 0})
        self.defaults = defaults
        self.devices = {d["id"]: Device(d, defaults, self.catalog) for d in lab.get("devices", [])}
        self.scenarios = {s["id"]: s for s in scenarios_doc.get("scenarios", [])}
        self.lock = threading.Lock()
        self.message = ""

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "app": APP_NAME,
                "lab_path": self.lab_path,
                "lab": {k: v for k, v in self.lab.items() if k != "devices"},
                "devices": [d.snapshot() for d in self.devices.values()],
                "catalog": self.catalog_doc.get("models", []),
                "scenarios": list(self.scenarios.values()),
                "message": self.message,
                "local_ip_hint": local_ip_hint(),
            }

    def apply_scenario(self, sid: str) -> None:
        scenario = self.scenarios.get(sid)
        if not scenario:
            self.message = f"Scenario not found: {sid}"
            return
        with self.lock:
            for dotted, value in scenario.get("set", {}).items():
                if "." not in dotted:
                    continue
                device_id, key = dotted.split(".", 1)
                if device_id in self.devices:
                    self.devices[device_id].set(key, value)
            self.message = f"Applied scenario: {scenario.get('name', sid)}"

    def toggle(self, device_id: str) -> None:
        with self.lock:
            if device_id in self.devices:
                self.devices[device_id].set("online", not bool(self.devices[device_id].get("online", True)))
                self.message = f"Toggled {device_id} online state."

    def set_state(self, device_id: str, key: str, value: Any) -> None:
        with self.lock:
            if device_id in self.devices and key:
                self.devices[device_id].set(key, value)
                self.message = f"Set {device_id}.{key} = {value}"

    def add_device(self, data: dict[str, Any]) -> tuple[Device | None, str]:
        model_key = data.get("model_key", "")
        device_id = data.get("id", "").strip()
        if not device_id:
            return None, "Device ID is required."
        if model_key not in self.catalog:
            return None, f"Unknown model: {model_key}"
        with self.lock:
            if device_id in self.devices:
                return None, f"Device already exists: {device_id}"
            port = int(data.get("port") or self.catalog[model_key].get("default_port", 0) or 0)
            if any(d.port == port and d.host == data.get("host", self.defaults.get("host", "0.0.0.0")) for d in self.devices.values()):
                return None, f"Port already in use in this lab: {port}"
            cfg = {
                "id": device_id,
                "name": data.get("name") or device_id,
                "model_key": model_key,
                "host": data.get("host") or self.defaults.get("host", "0.0.0.0"),
                "port": port,
                "state": {},
            }
            dev = Device(cfg, self.defaults, self.catalog)
            self.devices[dev.id] = dev
            self.message = f"Added device {dev.id}."
            return dev, self.message

    def remove_device(self, device_id: str) -> None:
        with self.lock:
            if device_id in self.devices:
                self.devices[device_id].set("online", False)
                del self.devices[device_id]
                self.message = f"Removed {device_id} from the profile. Restart app to free its old port if it was already listening."

    def save(self, target_path: str | None = None) -> str:
        target = target_path or self.lab_path
        with self.lock:
            lab = deepcopy({k: v for k, v in self.lab.items() if k != "devices"})
            lab.setdefault("lab_id", Path(target).stem)
            lab.setdefault("name", Path(target).stem.replace("_", " ").title())
            lab["devices"] = [d.to_lab_config() for d in self.devices.values()]
            save_json(target, lab)
            self.lab = lab
            self.lab_path = target
            self.message = f"Saved lab profile: {target}"
            return self.message


class TcpMock:
    def __init__(self, device: Device, log: CommandLog) -> None:
        self.d = device
        self.log = log
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.handle, self.d.host, self.d.port)
        print(f"{self.d.id}: TCP {self.d.host}:{self.d.port}")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = repr(writer.get_extra_info("peername"))
        if not self.d.get("online", True):
            writer.close()
            await writer.wait_closed()
            return
        if self.d.type == "pjlink_projector":
            writer.write(b"PJLINK 0\r\n")
            await writer.drain()
        while not reader.at_eof():
            data = await reader.read(4096)
            if not data:
                break
            text = data.decode(errors="replace").strip()
            self.log.add(self.d.id, "rx", text, peer)
            delay = int(self.d.get("response_delay_ms", 0) or 0)
            if delay:
                await asyncio.sleep(delay / 1000)
            resp = self.reply(text)
            if resp is not None:
                writer.write(resp)
                await writer.drain()
                self.log.add(self.d.id, "tx", resp.decode(errors="replace"), peer)
        writer.close()

    def reply(self, text: str) -> bytes:
        up = text.upper()
        custom = self.rule_reply(text)
        if custom is not None:
            return custom
        if self.d.type == "pjlink_projector":
            return self.pjlink(up)
        if self.d.type == "vaddio_camera":
            return self.vaddio(text, up)
        if self.d.type == "shure":
            return self.shure(up)
        if self.d.type == "display":
            return self.display(up)
        if self.d.type == "tesira":
            return b"+OK\r\n"
        return b"OK\r\n"

    def rule_reply(self, text: str) -> bytes | None:
        for rule in self.d.rules:
            contains = rule.get("contains", "")
            if contains and contains not in text:
                continue
            for key, value in rule.get("set_state", {}).items():
                self.d.set(key, value)
            if "response" in rule:
                return rule["response"].encode()
            if "response_state" in rule:
                return rule.get("format", "{value}\r\n").format(value=crestron_bool(self.d.get(rule["response_state"], ""))).encode()
        return None

    def pjlink(self, up: str) -> bytes:
        if "POWR ?" in up:
            return f"%1POWR={'1' if self.d.get('power') == 'on' else '0'}\r\n".encode()
        if "POWR 1" in up:
            self.d.set("power", "on")
            return b"%1POWR=OK\r\n"
        if "POWR 0" in up:
            self.d.set("power", "off")
            return b"%1POWR=OK\r\n"
        if "INPT ?" in up:
            return f"%1INPT={self.d.get('input','RGB1')}\r\n".encode()
        if "INPT " in up:
            self.d.set("input", up.split("INPT", 1)[1].strip())
            return b"%1INPT=OK\r\n"
        if "LAMP ?" in up:
            return f"%1LAMP={self.d.get('lamp_hours',0)} 1\r\n".encode()
        if "AVMT ?" in up:
            return f"%1AVMT={'31' if self.d.get('mute') else '30'}\r\n".encode()
        return b"%1ERR1\r\n"

    def vaddio(self, text: str, up: str) -> bytes:
        if "PRESET" in up and "RECALL" in up:
            digits = "".join(c for c in text if c.isdigit())
            self.d.set("preset", int(digits or 0))
            return b"OK\r\n"
        if "CAMERA HOME" in up:
            self.d.set("pan", 0)
            self.d.set("tilt", 0)
            self.d.set("zoom", 0)
            return b"OK\r\n"
        if "POWER" in up and "ON" in up:
            self.d.set("power", "on")
            return b"OK\r\n"
        if "POWER" in up and "OFF" in up:
            self.d.set("power", "off")
            return b"OK\r\n"
        return b"OK\r\n"

    def shure(self, up: str) -> bytes:
        if "GET DEVICE_ID" in up:
            return f"< REP DEVICE_ID {self.d.get('device_id', self.d.id)} >\r\n".encode()
        if "GET AUDIO_MUTE" in up:
            return f"< REP AUDIO_MUTE {self.d.get('audio_mute','OFF')} >\r\n".encode()
        if "SET AUDIO_MUTE ON" in up:
            self.d.set("audio_mute", "ON")
            return b"< REP AUDIO_MUTE ON >\r\n"
        if "SET AUDIO_MUTE OFF" in up:
            self.d.set("audio_mute", "OFF")
            return b"< REP AUDIO_MUTE OFF >\r\n"
        return b"< REP OK >\r\n"

    def display(self, up: str) -> bytes:
        if "POWR?" in up or "POWER?" in up:
            return f"POWR={self.d.get('power','off')}\r\n".encode()
        if "POWR1" in up or "POWER ON" in up:
            self.d.set("power", "on")
            return b"POWR=on\r\n"
        if "POWR0" in up or "POWER OFF" in up:
            self.d.set("power", "off")
            return b"POWR=off\r\n"
        return b"OK\r\n"


class UdpVisca:
    def __init__(self, device: Device, log: CommandLog) -> None:
        self.d = device
        self.log = log
        self.transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: self.Protocol(self), local_addr=(self.d.host, self.d.port))
        print(f"{self.d.id}: UDP {self.d.host}:{self.d.port}")

    class Protocol(asyncio.DatagramProtocol):
        def __init__(self, parent: "UdpVisca") -> None:
            self.p = parent

        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            self.p.log.add(self.p.d.id, "rx", data.hex(" "), repr(addr))
            if not self.p.d.get("online", True) or not self.p.transport:
                return
            for msg in (bytes.fromhex("90 41 ff"), bytes.fromhex("90 51 ff")):
                self.p.transport.sendto(msg, addr)
                self.p.log.add(self.p.d.id, "tx", msg.hex(" "), repr(addr))


class Runtime:
    def __init__(self, app: LabApp, log: CommandLog) -> None:
        self.app = app
        self.log = log
        self.loop: asyncio.AbstractEventLoop | None = None
        self.services: dict[str, Any] = {}

    async def start_all(self) -> None:
        self.loop = asyncio.get_running_loop()
        for d in list(self.app.devices.values()):
            await self.start_device(d)

    async def start_device(self, d: Device) -> None:
        if d.id in self.services:
            return
        try:
            if d.protocol == "udp" or d.type == "visca_udp_camera":
                service: Any = UdpVisca(d, self.log)
            elif d.protocol == "http" or d.type == "nvx_http":
                service = Web(self.app, self.log, d, d.host, d.port, self)
            else:
                service = TcpMock(d, self.log)
            await service.start()
            self.services[d.id] = service
        except OSError as exc:
            d.set("online", False)
            self.app.message = f"Failed to bind {d.id} on {d.host}:{d.port}: {exc}"

    def start_device_from_thread(self, d: Device) -> None:
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self.start_device(d), self.loop)


class Web:
    def __init__(self, app: LabApp, log: CommandLog, device: Device | None, host: str, port: int, runtime: Runtime | None = None) -> None:
        self.app = app
        self.log = log
        self.device = device
        self.host = host
        self.port = port
        self.runtime = runtime
        self.httpd: ThreadingHTTPServer | None = None

    async def start(self) -> None:
        parent = self

        class H(BaseHTTPRequestHandler):
            def send(self, code: int, body: str, ctype: str = "text/html") -> None:
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def redirect(self, target: str = "/") -> None:
                self.send_response(303)
                self.send_header("Location", target)
                self.end_headers()

            def do_GET(self) -> None:
                if parent.device:
                    return parent.nvx(self, "GET")
                if self.path == "/api/state":
                    return self.send(200, json.dumps(parent.app.snapshot(), indent=2), "application/json")
                if self.path == "/api/logs":
                    return self.send(200, json.dumps(parent.log.recent, indent=2), "application/json")
                return self.send(200, parent.dashboard())

            def do_POST(self) -> None:
                if parent.device:
                    return parent.nvx(self, "POST")
                form = parent.form(self)
                path = urlparse(self.path).path
                if path == "/device/toggle":
                    parent.app.toggle(form.get("id", [""])[0])
                    return self.redirect("/#devices")
                if path == "/device/state":
                    parent.app.set_state(form.get("id", [""])[0], form.get("key", [""])[0], parse_value(form.get("value", [""])[0]))
                    return self.redirect("/#devices")
                if path == "/device/add":
                    dev, _ = parent.app.add_device({k: v[0] for k, v in form.items()})
                    if dev and parent.runtime:
                        parent.runtime.start_device_from_thread(dev)
                    return self.redirect("/#builder")
                if path == "/device/remove":
                    parent.app.remove_device(form.get("id", [""])[0])
                    return self.redirect("/#devices")
                if path == "/lab/save":
                    target = form.get("path", [""])[0].strip() or None
                    parent.app.save(target)
                    return self.redirect("/#builder")
                if path == "/scenario/apply":
                    parent.app.apply_scenario(form.get("id", [""])[0])
                    return self.redirect("/#scenarios")
                return self.redirect("/")

            def do_PUT(self) -> None:
                if parent.device:
                    return parent.nvx(self, "PUT")
                return self.send(404, "not found", "text/plain")

            def log_message(self, *_: Any) -> None:
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        print(("Dashboard" if self.device is None else self.device.id) + f": HTTP {self.host}:{self.port}")

    @staticmethod
    def form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
        n = int(handler.headers.get("Content-Length", "0") or "0")
        return parse_qs(handler.rfile.read(n).decode(errors="replace") if n else "")

    def nvx(self, h: BaseHTTPRequestHandler, method: str) -> None:
        assert self.device is not None
        n = int(h.headers.get("Content-Length", "0") or "0")
        body = h.rfile.read(n).decode(errors="replace") if n else ""
        self.log.add(self.device.id, "rx", f"{method} {h.path} {body}")
        if not self.device.get("online", True):
            return self.send_json(h, 503, {"online": False, "device": self.device.id})
        if method in {"POST", "PUT"} and body:
            try:
                data = json.loads(body)
                for key in ("streamLocation", "stream_location", "power", "video_sync", "input", "route"):
                    if key in data:
                        self.device.set("stream_location" if key == "streamLocation" else key, data[key])
            except json.JSONDecodeError:
                pass
        st = self.device.snapshot()["state"]
        self.send_json(h, 200, {
            "device": self.device.id,
            "model": self.device.model,
            "role": st.get("role"),
            "streamLocation": st.get("stream_location"),
            "videoSync": st.get("video_sync", True),
            "online": st.get("online", True),
            "path": urlparse(h.path).path,
        })

    @staticmethod
    def send_json(h: BaseHTTPRequestHandler, code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    def dashboard(self) -> str:
        snap = self.app.snapshot()
        devices = snap["devices"]
        lab = snap["lab"]
        online = sum(1 for d in devices if d["state"].get("online"))
        rows = "".join(self.device_row(d) for d in devices)
        scenarios = "".join(self.scenario_card(s) for s in snap["scenarios"])
        catalog_rows = "".join(self.catalog_row(m) for m in snap["catalog"])
        model_options = "".join(f"<option value='{esc(m['key'])}'>{esc(m.get('vendor',''))} {esc(m.get('model',''))} · {esc(m.get('family',''))}</option>" for m in snap["catalog"])
        logs = "".join(f"<li><code>{esc(e['ts'])} {esc(e['device'])} {esc(e['dir'])} {esc(e['payload'])}</code></li>" for e in reversed(self.log.recent[-100:]))
        msg = f"<div class='notice'>{esc(snap['message'])}</div>" if snap.get("message") else ""
        return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{APP_NAME}</title><style>{CSS}</style></head><body><header><div><h1>{APP_NAME}</h1><p>{esc(lab.get('name','Lab'))} · {online}/{len(devices)} online · Lab PC IP hint: {esc(snap['local_ip_hint'])}</p></div><nav><a href='#devices'>Devices</a><a href='#builder'>Builder</a><a href='#scenarios'>Scenarios</a><a href='#catalog'>Catalog</a><a href='#logs'>Logs</a></nav></header><main>{msg}<section class='cards'><div class='card'><b>Active Lab</b><span>{esc(lab.get('lab_id','default'))}</span></div><div class='card'><b>Lab File</b><span>{esc(snap['lab_path'])}</span></div><div class='card'><b>Dashboard</b><span>:{self.port}</span></div><div class='card'><b>Device Count</b><span>{len(devices)}</span></div></section><section id='devices'><h2>Devices</h2><table><thead><tr><th>Device</th><th>Endpoint</th><th>State</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></section><section id='builder'><h2>Lab Builder</h2><div class='panel'><h3>Add device from catalog</h3><form method='post' action='/device/add' class='wide-form'><label>Device ID<input name='id' placeholder='nvx_desk_rx'></label><label>Name<input name='name' placeholder='Desk NVX RX'></label><label>Model<select name='model_key'>{model_options}</select></label><label>Host<input name='host' placeholder='0.0.0.0'></label><label>Port<input name='port' placeholder='unique port'></label><button>Add and Start</button></form><h3>Save lab profile</h3><form method='post' action='/lab/save' class='wide-form'><label>Path<input name='path' value='{esc(snap['lab_path'])}'></label><button>Save Profile</button></form></div></section><section id='scenarios'><h2>Scenarios</h2><div class='scenario-grid'>{scenarios}</div></section><section id='catalog'><h2>Device Catalog</h2><table><thead><tr><th>Model</th><th>Type</th><th>Protocol</th><th>Default Port</th></tr></thead><tbody>{catalog_rows}</tbody></table></section><section id='logs'><h2>Recent Commands</h2><ol>{logs}</ol></section></main></body></html>"""

    @staticmethod
    def device_row(d: dict[str, Any]) -> str:
        state = d["state"]
        status = "online" if state.get("online") else "offline"
        pills = "".join(f"<span class='pill'>{esc(k)}: {esc(v)}</span>" for k, v in state.items())
        keys = ["power", "input", "stream_location", "video_sync", "audio_mute", "response_delay_ms", "mute", "level", "fault", "usb_routed", "hdcp_state"]
        forms = "".join(f"<form method='post' action='/device/state' class='inline'><input type='hidden' name='id' value='{esc(d['id'])}'><input type='hidden' name='key' value='{esc(k)}'><input name='value' placeholder='{esc(state.get(k, ''))}'><button>Set {esc(k)}</button></form>" for k in keys if k in state)
        return f"<tr><td><b>{esc(d['name'])}</b><br><small>{esc(d['vendor'])} {esc(d['model'])}<br>{esc(d['id'])} · {esc(d['type'])}</small></td><td><code>{esc(d['protocol'])}://{esc(d['host'])}:{d['port']}</code></td><td><span class='status {status}'>{status}</span><div>{pills}</div></td><td><form method='post' action='/device/toggle' class='inline'><input type='hidden' name='id' value='{esc(d['id'])}'><button>Toggle Online</button></form><form method='post' action='/device/remove' class='inline'><input type='hidden' name='id' value='{esc(d['id'])}'><button class='danger'>Remove</button></form>{forms}</td></tr>"

    @staticmethod
    def scenario_card(s: dict[str, Any]) -> str:
        return f"<div class='scenario'><h3>{esc(s.get('name', s['id']))}</h3><p>{esc(s.get('description',''))}</p><form method='post' action='/scenario/apply'><input type='hidden' name='id' value='{esc(s['id'])}'><button>Apply</button></form></div>"

    @staticmethod
    def catalog_row(m: dict[str, Any]) -> str:
        return f"<tr><td><b>{esc(m.get('model',''))}</b><br><small>{esc(m.get('vendor',''))} · {esc(m.get('family',''))}</small><br><code>{esc(m.get('key',''))}</code></td><td>{esc(m.get('type',''))}</td><td>{esc(m.get('protocol',''))}</td><td>{esc(m.get('default_port',''))}</td></tr>"


CSS = """
:root{font-family:Segoe UI,Arial,sans-serif;color:#172033;background:#f4f6fa}body{margin:0}header{position:sticky;top:0;background:#111827;color:white;padding:18px 26px;display:flex;justify-content:space-between;gap:24px;align-items:center;box-shadow:0 2px 16px #0003;z-index:10}h1{margin:0;font-size:24px}header p{margin:4px 0 0;color:#cbd5e1}nav a{color:white;text-decoration:none;margin-left:18px;font-weight:600}main{padding:26px;max-width:1600px;margin:auto}section{margin-bottom:32px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.card,.scenario,.panel{background:white;border-radius:16px;padding:18px;box-shadow:0 8px 24px #1f293714}.card b{display:block;color:#475569}.card span{display:block;font-size:18px;margin-top:8px;word-break:break-all}.notice{background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;padding:12px 16px;border-radius:14px;margin-bottom:18px;font-weight:700}table{width:100%;border-collapse:separate;border-spacing:0 10px}th{text-align:left;color:#64748b;font-size:13px;padding:0 12px}td{background:white;padding:14px 12px;vertical-align:top;box-shadow:0 4px 16px #1f29370d}tr td:first-child{border-radius:14px 0 0 14px}tr td:last-child{border-radius:0 14px 14px 0}.status{display:inline-block;padding:5px 10px;border-radius:999px;font-weight:700;font-size:12px}.online{background:#dcfce7;color:#166534}.offline{background:#fee2e2;color:#991b1b}.pill{display:inline-block;background:#eef2ff;margin:4px 4px 0 0;padding:4px 8px;border-radius:999px;font-size:12px}.scenario-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}button{border:0;background:#2563eb;color:white;padding:8px 12px;border-radius:10px;font-weight:700;cursor:pointer;margin:4px}button:hover{background:#1d4ed8}.danger{background:#dc2626}.danger:hover{background:#b91c1c}input,select{padding:8px 10px;border:1px solid #cbd5e1;border-radius:9px;margin:5px 4px 5px 0;min-width:160px}label{font-weight:700;color:#475569;display:flex;flex-direction:column;margin:6px}.wide-form{display:flex;flex-wrap:wrap;align-items:end;gap:6px}.inline{display:inline-block}code{background:#f1f5f9;padding:2px 5px;border-radius:6px}small{color:#64748b}ol{background:white;border-radius:14px;padding:18px 18px 18px 42px;box-shadow:0 4px 16px #1f29370d;overflow:auto;max-height:420px}
"""


async def run() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--lab", default=DEFAULT_LAB)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()

    lab = load_json(args.lab)
    if not lab and Path("config/devices.json").exists():
        lab = {"lab_id": "legacy", "name": "Legacy devices.json Lab", **load_json("config/devices.json")}
    app = LabApp(args.lab, lab, load_json(args.catalog, {"models": []}), load_json(args.scenarios, {"scenarios": []}))
    log = CommandLog()
    runtime = Runtime(app, log)
    await runtime.start_all()

    dash = lab.get("dashboard", {"host": "0.0.0.0", "port": 8080})
    dashboard = Web(app, log, None, dash.get("host", "0.0.0.0"), int(dash.get("port", 8080)), runtime)
    await dashboard.start()
    url = f"http://127.0.0.1:{dash.get('port', 8080)}"
    print(f"\nDashboard: {url}\nPress Ctrl+C to stop.\n")
    if args.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Stopping.")
