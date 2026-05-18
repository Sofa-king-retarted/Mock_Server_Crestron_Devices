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

    def peers(self) -> set[str]:
        with self.lock:
            return {entry.get("peer", "") for entry in self.recent if entry.get("peer")}

    def device_activity(self, peer_contains: str = "", direction: str = "rx") -> dict[str, dict[str, Any]]:
        activity: dict[str, dict[str, Any]] = {}
        with self.lock:
            entries = list(self.recent)

        for entry in entries:
            if direction and entry.get("dir") != direction:
                continue
            if peer_contains and peer_contains not in entry.get("peer", ""):
                continue
            activity[entry["device"]] = entry

        return activity

    def device_activity_history(
        self,
        peer_contains: str = "",
        direction: str = "rx",
        limit_per_device: int = 8,
    ) -> dict[str, list[dict[str, Any]]]:
        history: dict[str, list[dict[str, Any]]] = {}
        with self.lock:
            entries = list(self.recent)

        for entry in reversed(entries):
            if direction and entry.get("dir") != direction:
                continue
            if peer_contains and peer_contains not in entry.get("peer", ""):
                continue

            device_history = history.setdefault(entry["device"], [])
            if len(device_history) < limit_per_device:
                device_history.append(entry)

        return history

    def clear_recent(self) -> None:
        with self.lock:
            self.recent = []


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
        if str(lab.get("nvx_control", "")).lower() == "tcp":
            for device in self.devices.values():
                if device.type == "nvx_http":
                    device.type = "nvx_tcp"
                    device.protocol = "tcp"
        lab_id = str(lab.get("lab_id", "legacy"))
        self.scenarios = {
            s["id"]: s
            for s in scenarios_doc.get("scenarios", [])
            if not s.get("labs") or lab_id in s.get("labs", [])
        }
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
            for key, value in scenario.get("set_all", {}).items():
                for device in self.devices.values():
                    device.set(key, value)
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
            return self.projector(text, up)
        if self.d.type == "nvx_tcp":
            return self.nvx(text, up)
        if self.d.type == "vaddio_camera":
            return self.vaddio(text, up)
        if self.d.type == "shure":
            return self.shure(up)
        if self.d.type == "display":
            return self.display(up)
        if self.d.type == "tesira":
            return self.tesira(text, up)
        return b"OK\r\n"

    def nvx(self, text: str, up: str) -> bytes:
        if up.startswith("ROUTE "):
            parts = text.split()
            if len(parts) >= 3:
                stream = parts[2]
                self.d.set("route", parts[1])
                self.d.set("stream_location", stream.split(":", 1)[0])
                self.d.set("stream_port", parse_value(stream.split(":", 1)[1]) if ":" in stream else None)
                self.d.set("video_sync", True)
            return b"OK\r\n"
        if up.startswith("BLANK "):
            self.d.set("route", "")
            self.d.set("video_sync", False)
            return b"OK\r\n"
        if up.startswith("GET") or up.endswith("?"):
            return json.dumps({
                "device": self.d.id,
                "streamLocation": self.d.get("stream_location"),
                "videoSync": self.d.get("video_sync", True),
                "online": self.d.get("online", True),
            }).encode() + b"\r\n"
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

    def projector(self, text: str, up: str) -> bytes:
        if up.startswith("PWR?"):
            return f"PWR={self.d.get('power','off')}\r\n".encode()
        if up.startswith("PWR ON"):
            self.d.set("power", "on")
            return b":\r\n"
        if up.startswith("PWR OFF"):
            self.d.set("power", "off")
            return b":\r\n"
        if up.startswith("MUTE ON"):
            self.d.set("mute", True)
            return b":\r\n"
        if up.startswith("MUTE OFF"):
            self.d.set("mute", False)
            return b":\r\n"
        if up.startswith("SOURCE "):
            self.d.set("input", text.split(None, 1)[1].strip())
            return b":\r\n"
        if up.startswith("SOURCE?"):
            return f"SOURCE={self.d.get('input','30')}\r\n".encode()

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
        if "CAMERA PAN LEFT" in up:
            self.d.set("pan", int(self.d.get("pan", 0)) - 1)
            self.d.set("motion", "pan_left")
            return b"OK\r\n"
        if "CAMERA PAN RIGHT" in up:
            self.d.set("pan", int(self.d.get("pan", 0)) + 1)
            self.d.set("motion", "pan_right")
            return b"OK\r\n"
        if "CAMERA TILT UP" in up:
            self.d.set("tilt", int(self.d.get("tilt", 0)) + 1)
            self.d.set("motion", "tilt_up")
            return b"OK\r\n"
        if "CAMERA TILT DOWN" in up:
            self.d.set("tilt", int(self.d.get("tilt", 0)) - 1)
            self.d.set("motion", "tilt_down")
            return b"OK\r\n"
        if "CAMERA ZOOM IN" in up:
            self.d.set("zoom", int(self.d.get("zoom", 0)) + 1)
            self.d.set("motion", "zoom_in")
            return b"OK\r\n"
        if "CAMERA ZOOM OUT" in up:
            self.d.set("zoom", int(self.d.get("zoom", 0)) - 1)
            self.d.set("motion", "zoom_out")
            return b"OK\r\n"
        if "CAMERA STOP" in up:
            self.d.set("motion", "stopped")
            return b"OK\r\n"
        if "PRESET" in up and "RECALL" in up:
            digits = "".join(c for c in text if c.isdigit())
            self.d.set("preset", int(digits or 0))
            return b"OK\r\n"
        if "PRESET" in up and "STORE" in up:
            digits = "".join(c for c in text if c.isdigit())
            self.d.set("stored_preset", int(digits or 0))
            return b"OK\r\n"
        if "CAMERA HOME" in up:
            self.d.set("pan", 0)
            self.d.set("tilt", 0)
            self.d.set("zoom", 0)
            self.d.set("motion", "home")
            return b"OK\r\n"
        if "POWER" in up and "ON" in up:
            self.d.set("power", "on")
            return b"OK\r\n"
        if "POWER" in up and "OFF" in up:
            self.d.set("power", "off")
            return b"OK\r\n"
        return b"OK\r\n"

    def tesira(self, text: str, up: str) -> bytes:
        low = text.strip().lower()

        if low.startswith("device recallpreset"):
            preset = "".join(c for c in text if c.isdigit())
            self.d.set("last_preset", int(preset or 0))
            return b"+OK\r\n"

        level_idx = low.find(" set level ")
        if level_idx >= 0:
            tag = text[:level_idx].strip()
            args = text[level_idx + len(" set level "):].split()
            channel = args[0] if args else "1"
            value = parse_value(args[1]) if len(args) > 1 else 0
            self.d.set(self.tesira_key(tag, "level", channel), value)
            self.d.set("last_level_tag", tag)
            self.d.set("last_level_value", value)
            return b"+OK\r\n"

        mute_idx = low.find(" set mute ")
        if mute_idx >= 0:
            tag = text[:mute_idx].strip()
            args = text[mute_idx + len(" set mute "):].split()
            channel = args[0] if args else "1"
            value = parse_value(args[1]) if len(args) > 1 else True
            self.d.set(self.tesira_key(tag, "mute", channel), value)
            self.d.set("last_mute_tag", tag)
            self.d.set("last_mute_value", value)
            return b"+OK\r\n"

        level_get_idx = low.find(" get level")
        if level_get_idx >= 0:
            tag = text[:level_get_idx].strip()
            return f"+OK {self.d.get(self.tesira_key(tag, 'level', '1'), 0)}\r\n".encode()

        mute_get_idx = low.find(" get mute")
        if mute_get_idx >= 0:
            tag = text[:mute_get_idx].strip()
            return f"+OK {crestron_bool(self.d.get(self.tesira_key(tag, 'mute', '1'), False))}\r\n".encode()

        return b"+OK\r\n"

    @staticmethod
    def tesira_key(tag: str, control: str, channel: str) -> str:
        safe = "".join(c.lower() if c.isalnum() else "_" for c in tag).strip("_")
        return f"tesira_{safe}_{control}_{channel}"

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


def self_test_targets(app: LabApp) -> list[dict[str, Any]]:
    devices = app.devices
    targets: list[dict[str, Any]] = []

    def add(device_id: str, label: str, command: str) -> None:
        device = devices.get(device_id)
        if device is None:
            return
        if device.protocol != "tcp":
            return
        targets.append({
            "device_id": device_id,
            "label": label,
            "host": device.host,
            "port": device.port,
            "command": command,
        })

    for suffix in ("a", "b", "c"):
        add(f"projector_{suffix}", f"Projector {suffix.upper()}", "PWR?\r")
        add(f"sharp_tv_{suffix}", f"Sharp TV {suffix.upper()}", "POWR?\r")

    add("BIAMP-TESIRA", "Biamp Tesira", "DEVICE get version\n")

    for room in ("A", "B", "C"):
        add(f"VADDIO-{room}-FRONT", f"Vaddio {room} Front", "camera stop\n")
        add(f"VADDIO-{room}-REAR", f"Vaddio {room} Rear", "camera stop\n")

    add("DM-NVX-D30-A-TV", "NVX A TV route", "ROUTE DM-NVX-36x-A-Laptop 239.10.50.12:5004\r")
    add("DM-NVX-D30C-505-AVBridge", "NVX A projector route", "ROUTE DM-NVX-36x-A-Laptop 239.10.50.12:5004\r")

    return targets


def run_self_test(app: LabApp, timeout: float = 1.5) -> dict[str, Any]:
    results = []

    for target in self_test_targets(app):
        host = str(target["host"])
        connect_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        port = int(target["port"])
        command = str(target["command"])

        try:
            with socket.create_connection((connect_host, port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                sock.sendall(command.encode("ascii"))
                try:
                    response = sock.recv(4096).decode(errors="replace")
                except socket.timeout:
                    response = ""
            results.append({**target, "ok": True, "response": response.strip()})
        except OSError as exc:
            results.append({**target, "ok": False, "error": str(exc)})

    passed = sum(1 for result in results if result["ok"])
    total = len(results)
    summary = f"Self-test {passed}/{total} mock TCP paths passed."
    if passed != total:
        first_failure = next((result for result in results if not result["ok"]), None)
        if first_failure is not None:
            summary += f" First failure: {first_failure['label']}."

    app.message = summary
    return {
        "summary": summary,
        "passed": passed,
        "total": total,
        "results": results,
    }


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
                if self.path == "/api/cp4n-activity":
                    return self.send(200, json.dumps(parent.cp4n_activity(), indent=2), "application/json")
                if self.path == "/api/cp4n-audit":
                    return self.send(200, json.dumps(parent.cp4n_command_audit(), indent=2), "application/json")
                if self.path == "/api/processor-readiness":
                    return self.send(200, json.dumps(parent.processor_readiness(), indent=2), "application/json")
                if self.path == "/api/self-test":
                    return self.send(200, json.dumps(run_self_test(parent.app), indent=2), "application/json")
                return self.send(200, parent.dashboard(self.path))

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
                if path == "/self-test/run":
                    run_self_test(parent.app)
                    return self.redirect("/#logs")
                if path == "/scenario/apply":
                    parent.app.apply_scenario(form.get("id", [""])[0])
                    return self.redirect("/#scenarios")
                if path == "/logs/clear":
                    parent.log.clear_recent()
                    parent.app.message = "Cleared recent command log."
                    return self.redirect("/#logs")
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

    def dashboard(self, request_path: str = "/") -> str:
        snap = self.app.snapshot()
        devices = snap["devices"]
        lab = snap["lab"]
        live_refresh = parse_qs(urlparse(request_path).query).get("live", ["0"])[0] == "1"
        refresh_tag = "<meta http-equiv='refresh' content='5'>" if live_refresh else ""
        live_card = (
            "<div class='card ok'><b>Live Refresh</b><span>On</span><a class='button-link' href='/#logs'>Pause</a><small>Reloads every 5 seconds.</small></div>"
            if live_refresh
            else "<div class='card'><b>Live Refresh</b><span>Off</span><a class='button-link' href='/?live=1#logs'>Start</a><small>Use while watching CP4N traffic.</small></div>"
        )
        online = sum(1 for d in devices if d["state"].get("online"))
        peers = sorted(self.log.peers())
        cp4n_activity = self.cp4n_activity()
        cp4n_seen = cp4n_activity["seen"]
        rows = "".join(
            self.device_row(
                d,
                cp4n_activity["devices"].get(d["id"]),
                cp4n_activity["history"].get(d["id"], []),
                self.cp4n_expects_direct_command(d),
            )
            for d in devices
        )
        scenarios = "".join(self.scenario_card(s) for s in snap["scenarios"])
        catalog_rows = "".join(self.catalog_row(m) for m in snap["catalog"])
        model_options = "".join(f"<option value='{esc(m['key'])}'>{esc(m.get('vendor',''))} {esc(m.get('model',''))} · {esc(m.get('family',''))}</option>" for m in snap["catalog"])
        logs = "".join(f"<li><code>{esc(e['ts'])} {esc(e['device'])} {esc(e['dir'])} {esc(e['payload'])}</code></li>" for e in reversed(self.log.recent[-100:]))
        last_seen_text = cp4n_activity.get("last_seen_age_text") or "no CP4N command seen yet"
        cp4n_card = f"<div class='card {'ok' if cp4n_seen else 'warn'}'><b>CP4N Traffic</b><span>{esc(cp4n_activity['summary'])}</span><small>Last seen: {esc(last_seen_text)}<br>{esc(', '.join(peers[-4:]) or 'no command peers yet')}</small></div>"
        audit = self.cp4n_command_audit()
        audit_rows = "".join(self.audit_row(item) for item in audit["checks"])
        audit_card = f"<div class='card {'ok' if audit['passed'] == audit['total'] else 'warn'}'><b>Command Audit</b><span>{audit['passed']}/{audit['total']} checks passed</span><small>{esc(audit['summary'])}</small></div>"
        readiness = self.processor_readiness()
        readiness_rows = "".join(self.readiness_row(item) for item in readiness["checks"])
        readiness_card = f"<div class='card {'ok' if readiness['ready'] else 'warn'}'><b>Processor Readiness</b><span>{esc(readiness['status'])}</span><small>{esc(readiness['summary'])}</small></div>"
        readiness_section = f"<section id='readiness'><h2>Processor Readiness</h2><div class='panel'><p>{esc(readiness['summary'])}</p><p><b>Mock URL for CP4N lab profile:</b> <code>{esc(readiness['mock_url'])}</code></p><table><thead><tr><th>Check</th><th>Details</th><th>Status</th></tr></thead><tbody>{readiness_rows}</tbody></table></div></section>"
        msg = f"<div class='notice'>{esc(snap['message'])}</div>" if snap.get("message") else ""
        html = f"""<!doctype html><html><head><meta charset='utf-8'>{refresh_tag}<meta name='viewport' content='width=device-width,initial-scale=1'><title>{APP_NAME}</title><style>{CSS}</style></head><body><header><div><h1>{APP_NAME}</h1><p>{esc(lab.get('name','Lab'))} · {online}/{len(devices)} online · Lab PC IP hint: {esc(snap['local_ip_hint'])}</p></div><nav><a href='#devices'>Devices</a><a href='#audit'>Audit</a><a href='#builder'>Builder</a><a href='#scenarios'>Scenarios</a><a href='#catalog'>Catalog</a><a href='#logs'>Logs</a></nav></header><main>{msg}<section class='cards'><div class='card'><b>Active Lab</b><span>{esc(lab.get('lab_id','default'))}</span></div><div class='card'><b>Lab File</b><span>{esc(snap['lab_path'])}</span></div><div class='card'><b>Dashboard</b><span>:{self.port}</span></div><div class='card'><b>Device Count</b><span>{len(devices)}</span></div><div class='card'><b>Mock Self-Test</b><span>TCP paths</span><form method='post' action='/self-test/run'><button>Run Self Test</button></form><small>Projector, TV, Tesira, Vaddio, NVX</small></div>{cp4n_card}{audit_card}{live_card}</section><section id='devices'><h2>Devices</h2><table><thead><tr><th>Device</th><th>Endpoint</th><th>State</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></section><section id='audit'><h2>CP4N Command Audit</h2><table><thead><tr><th>Check</th><th>Expected</th><th>Matched Payload</th><th>Status</th></tr></thead><tbody>{audit_rows}</tbody></table></section><section id='builder'><h2>Lab Builder</h2><div class='panel'><h3>Add device from catalog</h3><form method='post' action='/device/add' class='wide-form'><label>Device ID<input name='id' placeholder='nvx_desk_rx'></label><label>Name<input name='name' placeholder='Desk NVX RX'></label><label>Model<select name='model_key'>{model_options}</select></label><label>Host<input name='host' placeholder='0.0.0.0'></label><label>Port<input name='port' placeholder='unique port'></label><button>Add and Start</button></form><h3>Save lab profile</h3><form method='post' action='/lab/save' class='wide-form'><label>Path<input name='path' value='{esc(snap['lab_path'])}'></label><button>Save Profile</button></form></div></section><section id='scenarios'><h2>Scenarios</h2><div class='scenario-grid'>{scenarios}</div></section><section id='catalog'><h2>Device Catalog</h2><table><thead><tr><th>Model</th><th>Type</th><th>Protocol</th><th>Default Port</th></tr></thead><tbody>{catalog_rows}</tbody></table></section><section id='logs'><h2>Recent Commands</h2><form method='post' action='/logs/clear'><button>Clear Logs</button></form><ol>{logs}</ol></section></main></body></html>"""
        html = html.replace("<nav><a href='#devices'>", "<nav><a href='#readiness'>Readiness</a><a href='#devices'>")
        html = html.replace(f"{cp4n_card}{audit_card}{live_card}", f"{readiness_card}{cp4n_card}{audit_card}{live_card}")
        html = html.replace("<section id='devices'>", readiness_section + "<section id='devices'>")
        return html

    def cp4n_activity(self, controller_ip: str = "192.168.1.2") -> dict[str, Any]:
        devices = self.app.snapshot()["devices"]
        activity = self.log.device_activity(controller_ip, "rx")
        activity_history = self.log.device_activity_history(controller_ip, "rx")
        device_activity = {
            device["id"]: activity[device["id"]]
            for device in devices
            if device["id"] in activity
        }
        device_history = {
            device["id"]: activity_history[device["id"]]
            for device in devices
            if device["id"] in activity_history
        }
        expected_devices = [device for device in devices if self.cp4n_expects_direct_command(device)]
        expected_touched = sum(1 for device in expected_devices if device["id"] in device_activity)
        touched = len(device_activity)
        total = len(devices)
        expected_total = len(expected_devices)
        activity_entries = [entry for entries in device_history.values() for entry in entries]
        last_seen = max(activity_entries, key=lambda entry: entry["ts"]) if activity_entries else None
        summary = (
            f"seen from {controller_ip}; touched {expected_touched}/{expected_total} expected direct-control devices"
            if touched
            else f"not seen from {controller_ip} yet"
        )

        return {
            "controller_ip": controller_ip,
            "seen": touched > 0,
            "touched": touched,
            "total": total,
            "expected_touched": expected_touched,
            "expected_total": expected_total,
            "inventory_only": total - expected_total,
            "last_seen": last_seen["ts"] if last_seen else None,
            "last_seen_age_seconds": self.activity_age_seconds(last_seen["ts"]) if last_seen else None,
            "last_seen_age_text": self.activity_age_text(last_seen["ts"]) if last_seen else None,
            "summary": summary,
            "devices": device_activity,
            "history": device_history,
        }

    @staticmethod
    def activity_age_seconds(timestamp: str) -> int:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))

    @staticmethod
    def activity_age_text(timestamp: str) -> str:
        seconds = Web.activity_age_seconds(timestamp)
        if seconds < 60:
            return f"{seconds}s ago"

        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"

        hours = minutes // 60
        return f"{hours}h ago"

    def cp4n_command_audit(self, controller_ip: str = "192.168.1.2") -> dict[str, Any]:
        devices = {device["id"]: device for device in self.app.snapshot()["devices"]}
        history = self.log.device_activity_history(controller_ip, "rx", limit_per_device=16)
        checks: list[dict[str, Any]] = []

        def payloads(device_id: str) -> list[str]:
            return [entry["payload"] for entry in history.get(device_id, [])]

        def add(device_id: str, label: str, expected: str, contains: str) -> None:
            matched = next((payload for payload in payloads(device_id) if contains in payload), "")
            checks.append({
                "device_id": device_id,
                "label": label,
                "expected": expected,
                "matched": matched,
                "ok": bool(matched),
            })

        for suffix, room in (("a", "A"), ("b", "B"), ("c", "C")):
            projector = f"projector_{suffix}"
            add(projector, f"Room {room} projector power", "PWR ON", "PWR ON")
            add(projector, f"Room {room} projector video mute cleared", "MUTE OFF", "MUTE OFF")
            add(f"sharp_tv_{suffix}", f"Room {room} Sharp TV show", f"RM-{room}-TV-SHOW", f"RM-{room}-TV-SHOW")

        source_id = "DM-NVX-36x-A-Laptop"
        source = devices.get(source_id, {})
        source_state = source.get("state", {})
        stream_location = source_state.get("stream_location", "")
        stream_port = source_state.get("stream_port", 5004)
        expected_route = f"ROUTE {source_id} {stream_location}:{stream_port}"
        for room in ("A", "B", "C"):
            add(
                f"DM-NVX-D30-{room}-TV",
                f"Room {room} TV NVX route",
                expected_route,
                expected_route,
            )

        for room_number in ("505", "506", "507"):
            add(
                "BIAMP-TESIRA",
                f"Room {room_number} Tesira volume",
                f"{room_number}-Vol set level 1 32768",
                f"{room_number}-Vol set level 1 32768",
            )

        for room in ("A", "B", "C"):
            for position in ("FRONT", "REAR"):
                device_id = f"VADDIO-{room}-{position}"
                label_prefix = f"Room {room} {position.title()} camera"
                add(device_id, f"{label_prefix} zoom", "camera zoom in", "camera zoom in")
                add(device_id, f"{label_prefix} stop", "camera stop", "camera stop")

        passed = sum(1 for check in checks if check["ok"])
        total = len(checks)
        summary = f"CP4N command audit {passed}/{total} checks passed."
        if passed != total:
            failed = next(check for check in checks if not check["ok"])
            summary += f" First missing: {failed['label']} expected {failed['expected']}."

        return {
            "summary": summary,
            "passed": passed,
            "total": total,
            "checks": checks,
        }

    def processor_readiness(self, controller_ip: str = "192.168.1.2") -> dict[str, Any]:
        activity = self.cp4n_activity(controller_ip)
        audit = self.cp4n_command_audit(controller_ip)
        smart_graphics_open = self.tcp_port_open(controller_ip, 41794)
        ssh_open = self.tcp_port_open(controller_ip, 22)
        mock_url = f"http://{local_ip_hint()}:{self.port}"
        checks = [
            {
                "label": "Mock server URL",
                "detail": f"Use {mock_url} as the lab PC target host for CP4N tests.",
                "ok": True,
            },
            {
                "label": "CP4N network reachability",
                "detail": f"SSH port 22 on {controller_ip} is {'open' if ssh_open else 'closed'} from this PC.",
                "ok": ssh_open,
            },
            {
                "label": "CP4N Smart Graphics service",
                "detail": f"Port 41794 on {controller_ip} is {'open' if smart_graphics_open else 'closed'} from this PC.",
                "ok": smart_graphics_open,
            },
            {
                "label": "CP4N has contacted mock devices",
                "detail": activity["summary"],
                "ok": activity["seen"],
            },
            {
                "label": "Expected startup/control commands",
                "detail": audit["summary"],
                "ok": audit["passed"] == audit["total"],
            },
        ]
        blockers = [check["label"] for check in checks if not check["ok"]]
        ready = not blockers
        status = "ready" if ready else "blocked"
        summary = (
            "Processor traffic matches the DOE mock expectations."
            if ready
            else "Waiting on: " + ", ".join(blockers) + "."
        )

        return {
            "controller_ip": controller_ip,
            "mock_url": mock_url,
            "ready": ready,
            "status": status,
            "summary": summary,
            "checks": checks,
        }

    @staticmethod
    def tcp_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def cp4n_expects_direct_command(d: dict[str, Any]) -> bool:
        if d["type"] in {"pjlink_projector", "tesira", "vaddio_camera"}:
            return True

        if d["type"] == "display":
            return d.get("model_key") == "generic_display_tcp" or d["id"].startswith("sharp_tv_")

        if d["type"] == "nvx_http" and d.get("model_key") == "crestron_dm_nvx_d30" and "-TV" in d["id"]:
            return True

        if d["type"] == "nvx_tcp":
            state = d["state"]
            return state.get("role") == "receiver" and "-TV" in d["id"]

        return False

    @staticmethod
    def device_row(
        d: dict[str, Any],
        cp4n_entry: dict[str, Any] | None = None,
        cp4n_history: list[dict[str, Any]] | None = None,
        expects_cp4n_direct_command: bool = True,
    ) -> str:
        state = d["state"]
        status = "online" if state.get("online") else "offline"
        pills = "".join(f"<span class='pill'>{esc(k)}: {esc(v)}</span>" for k, v in state.items())
        if cp4n_entry:
            history_items = "".join(
                f"<li><small>{esc(entry['ts'])}</small><code>{esc(entry['payload'])}</code></li>"
                for entry in cp4n_history or [cp4n_entry]
            )
            cp4n_status = f"<div class='cp4n-hit'><details open><summary><span class='status online'>CP4N seen</span> <small>{len(cp4n_history or [cp4n_entry])} command(s)</small></summary><ol class='cp4n-command-list'>{history_items}</ol></details></div>"
        elif expects_cp4n_direct_command:
            cp4n_status = "<div class='cp4n-hit'><span class='status offline'>CP4N not hit</span><small>No recent rx command from 192.168.1.2.</small></div>"
        else:
            cp4n_status = "<div class='cp4n-hit'><span class='status neutral'>Inventory only</span><small>Health/config device; no direct startup TCP command expected.</small></div>"
        pills = cp4n_status + pills
        keys = ["power", "input", "stream_location", "video_sync", "audio_mute", "response_delay_ms", "mute", "level", "fault", "usb_routed", "hdcp_state"]
        forms = "".join(f"<form method='post' action='/device/state' class='inline'><input type='hidden' name='id' value='{esc(d['id'])}'><input type='hidden' name='key' value='{esc(k)}'><input name='value' placeholder='{esc(state.get(k, ''))}'><button>Set {esc(k)}</button></form>" for k in keys if k in state)
        return f"<tr><td><b>{esc(d['name'])}</b><br><small>{esc(d['vendor'])} {esc(d['model'])}<br>{esc(d['id'])} · {esc(d['type'])}</small></td><td><code>{esc(d['protocol'])}://{esc(d['host'])}:{d['port']}</code></td><td><span class='status {status}'>{status}</span><div>{pills}</div></td><td><form method='post' action='/device/toggle' class='inline'><input type='hidden' name='id' value='{esc(d['id'])}'><button>Toggle Online</button></form><form method='post' action='/device/remove' class='inline'><input type='hidden' name='id' value='{esc(d['id'])}'><button class='danger'>Remove</button></form>{forms}</td></tr>"

    @staticmethod
    def audit_row(item: dict[str, Any]) -> str:
        status = "online" if item["ok"] else "offline"
        status_text = "pass" if item["ok"] else "missing"
        matched = item["matched"] or "No matching CP4N payload logged."
        return f"<tr><td><b>{esc(item['label'])}</b><br><small>{esc(item['device_id'])}</small></td><td><code>{esc(item['expected'])}</code></td><td><code>{esc(matched)}</code></td><td><span class='status {status}'>{status_text}</span></td></tr>"

    @staticmethod
    def readiness_row(item: dict[str, Any]) -> str:
        status = "online" if item["ok"] else "offline"
        status_text = "pass" if item["ok"] else "blocked"
        return f"<tr><td><b>{esc(item['label'])}</b></td><td>{esc(item['detail'])}</td><td><span class='status {status}'>{status_text}</span></td></tr>"

    @staticmethod
    def scenario_card(s: dict[str, Any]) -> str:
        return f"<div class='scenario'><h3>{esc(s.get('name', s['id']))}</h3><p>{esc(s.get('description',''))}</p><form method='post' action='/scenario/apply'><input type='hidden' name='id' value='{esc(s['id'])}'><button>Apply</button></form></div>"

    @staticmethod
    def catalog_row(m: dict[str, Any]) -> str:
        return f"<tr><td><b>{esc(m.get('model',''))}</b><br><small>{esc(m.get('vendor',''))} · {esc(m.get('family',''))}</small><br><code>{esc(m.get('key',''))}</code></td><td>{esc(m.get('type',''))}</td><td>{esc(m.get('protocol',''))}</td><td>{esc(m.get('default_port',''))}</td></tr>"


CSS = """
:root{font-family:Segoe UI,Arial,sans-serif;color:#172033;background:#f4f6fa}body{margin:0}header{position:sticky;top:0;background:#111827;color:white;padding:18px 26px;display:flex;justify-content:space-between;gap:24px;align-items:center;box-shadow:0 2px 16px #0003;z-index:10}h1{margin:0;font-size:24px}header p{margin:4px 0 0;color:#cbd5e1}nav a{color:white;text-decoration:none;margin-left:18px;font-weight:600}main{padding:26px;max-width:1600px;margin:auto}section{margin-bottom:32px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.card,.scenario,.panel{background:white;border-radius:16px;padding:18px;box-shadow:0 8px 24px #1f293714}.card.ok{border:2px solid #22c55e}.card.warn{border:2px solid #f59e0b}.card b{display:block;color:#475569}.card span{display:block;font-size:18px;margin-top:8px;word-break:break-all}.notice{background:#dbeafe;color:#1e40af;border:1px solid #93c5fd;padding:12px 16px;border-radius:14px;margin-bottom:18px;font-weight:700}table{width:100%;border-collapse:separate;border-spacing:0 10px}th{text-align:left;color:#64748b;font-size:13px;padding:0 12px}td{background:white;padding:14px 12px;vertical-align:top;box-shadow:0 4px 16px #1f29370d}tr td:first-child{border-radius:14px 0 0 14px}tr td:last-child{border-radius:0 14px 14px 0}.status{display:inline-block;padding:5px 10px;border-radius:999px;font-weight:700;font-size:12px}.online{background:#dcfce7;color:#166534}.offline{background:#fee2e2;color:#991b1b}.neutral{background:#e2e8f0;color:#334155}.pill{display:inline-block;background:#eef2ff;margin:4px 4px 0 0;padding:4px 8px;border-radius:999px;font-size:12px}.cp4n-hit{margin:6px 0 8px}.cp4n-hit summary{cursor:pointer;list-style:none}.cp4n-command-list{margin:8px 0 0;padding:8px 10px;max-height:180px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;box-shadow:none}.cp4n-command-list li{display:grid;gap:3px;margin:0 0 7px}.cp4n-command-list code{display:block;white-space:pre-wrap;word-break:break-word}.scenario-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}button{border:0;background:#2563eb;color:white;padding:8px 12px;border-radius:10px;font-weight:700;cursor:pointer;margin:4px}button:hover,.button-link:hover{background:#1d4ed8}.button-link{display:inline-block;text-decoration:none;border:0;background:#2563eb;color:white;padding:8px 12px;border-radius:10px;font-weight:700;cursor:pointer;margin:4px}.danger{background:#dc2626}.danger:hover{background:#b91c1c}input,select{padding:8px 10px;border:1px solid #cbd5e1;border-radius:9px;margin:5px 4px 5px 0;min-width:160px}label{font-weight:700;color:#475569;display:flex;flex-direction:column;margin:6px}.wide-form{display:flex;flex-wrap:wrap;align-items:end;gap:6px}.inline{display:inline-block}code{background:#f1f5f9;padding:2px 5px;border-radius:6px}small{color:#64748b}ol{background:white;border-radius:14px;padding:18px 18px 18px 42px;box-shadow:0 4px 16px #1f29370d;overflow:auto;max-height:420px}
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
