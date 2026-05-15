from __future__ import annotations

import argparse, asyncio, json, threading
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

class Log:
    def __init__(self) -> None:
        Path('logs').mkdir(exist_ok=True)
        self.path = Path('logs/commands.jsonl')
        self.recent: list[dict[str, Any]] = []
        self.lock = threading.Lock()
    def add(self, dev: str, direction: str, payload: Any, peer: str = '') -> None:
        entry = {'ts': datetime.now(timezone.utc).isoformat(), 'device': dev, 'dir': direction, 'peer': peer, 'payload': payload if isinstance(payload, str) else repr(payload)}
        with self.lock:
            self.path.open('a', encoding='utf-8').write(json.dumps(entry) + '\n')
            self.recent = (self.recent + [entry])[-100:]
        print(f"{entry['ts']} {dev} {direction} {entry['payload']}")

class Dev:
    def __init__(self, cfg: dict[str, Any], defaults: dict[str, Any]) -> None:
        self.id = cfg['id']; self.name = cfg.get('name', self.id); self.type = cfg['type']
        self.host = cfg.get('host', defaults.get('host', '0.0.0.0')); self.port = int(cfg['port'])
        self.rules = cfg.get('response_rules', [])
        self.state = {'online': cfg.get('online', defaults.get('online', True)), 'response_delay_ms': cfg.get('response_delay_ms', defaults.get('response_delay_ms', 0)), **deepcopy(cfg.get('state', {}))}
    def get(self, key: str, default: Any = None) -> Any: return self.state.get(key, default)
    def set(self, key: str, val: Any) -> None: self.state[key] = val
    def snap(self) -> dict[str, Any]: return {'id': self.id, 'name': self.name, 'type': self.type, 'host': self.host, 'port': self.port, 'state': deepcopy(self.state)}

class App:
    def __init__(self, cfg: dict[str, Any], scn: dict[str, Any]) -> None:
        self.cfg = cfg; self.devices = {d['id']: Dev(d, cfg.get('defaults', {})) for d in cfg.get('devices', [])}
        self.scenarios = {s['id']: s for s in scn.get('scenarios', [])}
    def scenario(self, sid: str) -> None:
        for dotted, val in self.scenarios[sid].get('set', {}).items():
            dev, key = dotted.split('.', 1)
            if dev in self.devices: self.devices[dev].set(key, val)
    def snap(self) -> dict[str, Any]: return {'devices': [d.snap() for d in self.devices.values()], 'scenarios': list(self.scenarios.values())}

def load(path: str) -> dict[str, Any]:
    return json.load(open(path, encoding='utf-8'))

def val(v: Any) -> str:
    return 'true' if v is True else 'false' if v is False else str(v)

class TcpServer:
    def __init__(self, d: Dev, log: Log) -> None: self.d = d; self.log = log; self.server = None
    async def start(self) -> None:
        self.server = await asyncio.start_server(self.handle, self.d.host, self.d.port)
        print(f'{self.d.id}: TCP {self.d.host}:{self.d.port}')
    async def stop(self) -> None:
        if self.server: self.server.close(); await self.server.wait_closed()
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = repr(writer.get_extra_info('peername'))
        if not self.d.get('online', True): writer.close(); return
        if self.d.type == 'pjlink_projector': writer.write(b'PJLINK 0\r\n'); await writer.drain()
        while not reader.at_eof():
            data = await reader.read(4096)
            if not data: break
            text = data.decode(errors='replace').strip(); self.log.add(self.d.id, 'rx', text, peer)
            if self.d.get('response_delay_ms', 0): await asyncio.sleep(int(self.d.get('response_delay_ms')) / 1000)
            resp = self.reply(text)
            if resp is not None:
                writer.write(resp); await writer.drain(); self.log.add(self.d.id, 'tx', resp.decode(errors='replace'), peer)
        writer.close()
    def reply(self, text: str) -> bytes | None:
        t = text.upper(); typ = self.d.type
        if typ == 'pjlink_projector':
            if 'POWR ?' in t: return f"%1POWR={'1' if self.d.get('power') == 'on' else '0'}\r\n".encode()
            if 'POWR 1' in t: self.d.set('power', 'on'); return b'%1POWR=OK\r\n'
            if 'POWR 0' in t: self.d.set('power', 'off'); return b'%1POWR=OK\r\n'
            if 'INPT ?' in t: return f"%1INPT={self.d.get('input','RGB1')}\r\n".encode()
            if 'LAMP ?' in t: return f"%1LAMP={self.d.get('lamp_hours',0)} 1\r\n".encode()
            return b'%1ERR1\r\n'
        if typ == 'vaddio_camera':
            if 'PRESET' in t and 'RECALL' in t:
                digs = ''.join(c for c in text if c.isdigit()); self.d.set('preset', int(digs or 0)); return b'OK\r\n'
            return b'OK\r\n'
        if typ == 'shure':
            if 'GET DEVICE_ID' in t: return f"< REP DEVICE_ID {self.d.get('device_id','SHURE-MOCK')} >\r\n".encode()
            if 'GET AUDIO_MUTE' in t: return f"< REP AUDIO_MUTE {self.d.get('audio_mute','OFF')} >\r\n".encode()
            if 'SET AUDIO_MUTE ON' in t: self.d.set('audio_mute','ON'); return b'< REP AUDIO_MUTE ON >\r\n'
            if 'SET AUDIO_MUTE OFF' in t: self.d.set('audio_mute','OFF'); return b'< REP AUDIO_MUTE OFF >\r\n'
        if typ == 'display':
            if 'POWR?' in t: return f"POWR={self.d.get('power','off')}\r\n".encode()
            if 'POWR1' in t or 'POWER ON' in t: self.d.set('power','on'); return b'POWR=on\r\n'
            if 'POWR0' in t or 'POWER OFF' in t: self.d.set('power','off'); return b'POWR=off\r\n'
        for r in self.d.rules:
            if r.get('contains','') in text:
                if 'response' in r: return r['response'].encode()
                return r.get('format','{value}\r\n').format(value=val(self.d.get(r.get('response_state'), ''))).encode()
        return b'+OK\r\n' if typ == 'tesira' else b'OK\r\n'

class UdpVisca:
    def __init__(self, d: Dev, log: Log) -> None: self.d = d; self.log = log; self.transport = None
    async def start(self) -> None:
        loop = asyncio.get_running_loop(); self.transport, _ = await loop.create_datagram_endpoint(lambda: self.P(self), local_addr=(self.d.host, self.d.port)); print(f'{self.d.id}: UDP {self.d.host}:{self.d.port}')
    async def stop(self) -> None:
        if self.transport: self.transport.close()
    class P(asyncio.DatagramProtocol):
        def __init__(self, p: 'UdpVisca') -> None: self.p = p
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            self.p.log.add(self.p.d.id, 'rx', data.hex(' '), repr(addr))
            if self.p.d.get('online', True):
                for msg in (bytes.fromhex('90 41 ff'), bytes.fromhex('90 51 ff')): self.p.transport.sendto(msg, addr)

class HttpServer:
    def __init__(self, app: App, log: Log, d: Dev | None, host: str, port: int) -> None:
        self.app = app; self.log = log; self.d = d; self.host = host; self.port = port; self.httpd = None
    async def start(self) -> None:
        parent = self
        class H(BaseHTTPRequestHandler):
            def send(self, code: int, body: str, ctype: str = 'text/html') -> None:
                data = body.encode(); self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
            def do_GET(self) -> None:
                if parent.d: return parent.nvx(self, 'GET')
                if self.path == '/api/state': return self.send(200, json.dumps(parent.app.snap(), indent=2), 'application/json')
                return self.send(200, parent.html())
            def do_POST(self) -> None:
                if parent.d: return parent.nvx(self, 'POST')
                n = int(self.headers.get('Content-Length','0') or '0'); sid = parse_qs(self.rfile.read(n).decode()).get('id',[''])[0]; parent.app.scenario(sid); self.send_response(303); self.send_header('Location','/'); self.end_headers()
            def do_PUT(self) -> None:
                if parent.d: return parent.nvx(self, 'PUT')
            def log_message(self, *_: Any) -> None: return
        self.httpd = ThreadingHTTPServer((self.host, self.port), H); threading.Thread(target=self.httpd.serve_forever, daemon=True).start(); print(f'HTTP {self.host}:{self.port}')
    async def stop(self) -> None:
        if self.httpd: self.httpd.shutdown(); self.httpd.server_close()
    def nvx(self, h: BaseHTTPRequestHandler, method: str) -> None:
        n = int(h.headers.get('Content-Length','0') or '0'); body = h.rfile.read(n).decode(errors='replace') if n else ''; self.log.add(self.d.id, 'rx', f'{method} {h.path} {body}')
        if not self.d.get('online', True): return h.send(503, '{"online":false}', 'application/json')
        if method in ('POST','PUT') and body:
            try: data = json.loads(body); self.d.set('stream_location', data.get('streamLocation') or data.get('stream_location') or self.d.get('stream_location'))
            except json.JSONDecodeError: pass
        s = self.d.snap()['state']; h.send(200, json.dumps({'device': self.d.id, 'role': s.get('role'), 'streamLocation': s.get('stream_location'), 'videoSync': s.get('video_sync', True), 'path': urlparse(h.path).path}, indent=2), 'application/json')
    def html(self) -> str:
        rows = ''.join(f"<tr><td>{d['id']}</td><td>{d['type']}</td><td>{d['host']}:{d['port']}</td><td><pre>{json.dumps(d['state'])}</pre></td></tr>" for d in self.app.snap()['devices'])
        buttons = ''.join(f"<form method='post' style='display:inline'><input name='id' type='hidden' value='{s['id']}'><button>{s['name']}</button></form>" for s in self.app.snap()['scenarios'])
        logs = ''.join(f"<li><code>{e['ts']} {e['device']} {e['dir']} {e['payload']}</code></li>" for e in reversed(self.log.recent[-50:]))
        return f"<html><head><meta http-equiv='refresh' content='5'><style>body{{font-family:Arial;margin:24px}}td,th{{border:1px solid #ccc;padding:8px}}table{{border-collapse:collapse;width:100%}}pre{{white-space:pre-wrap}}</style></head><body><h1>Crestron AV Lab Simulator</h1><h2>Scenarios</h2>{buttons}<h2>Devices</h2><table><tr><th>ID</th><th>Type</th><th>Endpoint</th><th>State</th></tr>{rows}</table><h2>Recent Commands</h2><ol>{logs}</ol></body></html>"

async def amain() -> None:
    p = argparse.ArgumentParser(); p.add_argument('--config', default='config/devices.json'); p.add_argument('--scenarios', default='config/scenarios.json'); a = p.parse_args()
    app = App(load(a.config), load(a.scenarios)); log = Log(); services: list[Any] = []
    for d in app.devices.values():
        services.append(UdpVisca(d, log) if d.type == 'visca_udp_camera' else HttpServer(app, log, d, d.host, d.port) if d.type == 'nvx_http' else TcpServer(d, log))
    dc = app.cfg.get('dashboard', {'host':'0.0.0.0','port':8080}); services.append(HttpServer(app, log, None, dc.get('host','0.0.0.0'), int(dc.get('port',8080))))
    for s in services: await s.start()
    print(f"Dashboard: http://127.0.0.1:{dc.get('port',8080)}   Press Ctrl+C to stop.")
    while True: await asyncio.sleep(3600)

def main() -> None:
    try: asyncio.run(amain())
    except KeyboardInterrupt: pass
if __name__ == '__main__': main()
