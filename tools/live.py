#!/usr/bin/env python3
"""Play one private match on the public play server with our bot; the empty seats are the server's own bots.

    python3 tools/live.py --map ../mechfight-kit/arena --out runs -- ../.venv/bin/python -u bot.py

The server speaks mechfight/1 over a WebSocket, plus a short lobby (ready / start / loaded). This bridge
relays it to the bot's stdin/stdout and records:
  <out>/<stamp>-<code>.bot.jsonl   our side: hello, a compact record of every observation, every action, end
  <out>/<stamp>-<code>.live.jsonl  the spectator feed (full-state frames) for offline analysis
Standard library only. One match per run; please keep runs few and sequential (it is a shared public server).
"""
import argparse
import base64
import json
import os
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HOST = "play.joinbuilders.org"
UA = "mechfight-bridge"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


class WebSocket:
    """Minimal RFC 6455 client: text messages, fragments, ping/pong, masked client frames."""

    def __init__(self, path):
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(socket.create_connection((HOST, 443), timeout=20), server_hostname=HOST)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: https://{HOST}\r\n"
                           f"User-Agent: {UA}\r\n\r\n").encode())
        head = bytearray()
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed during the handshake")
            head += chunk
        status, _, rest = bytes(head).partition(b"\r\n\r\n")
        if b" 101" not in status.split(b"\r\n")[0]:
            raise ConnectionError(status.decode(errors="replace")[:300])
        self.buf = bytearray(rest)
        self.lock = threading.Lock()
        self.sock.settimeout(None)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def recv(self):
        parts = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(c ^ mask[i & 3] for i, c in enumerate(data))
            op = b0 & 0x0F
            if op == 0x8:
                raise EOFError
            if op == 0x9:
                self._send(0xA, data)
                continue
            if op == 0xA:
                continue
            parts.append(data)
            if b0 & 0x80:
                return b"".join(parts).decode("utf-8", errors="replace")

    def _send(self, op, payload):
        mask = secrets.token_bytes(4)
        n = len(payload)
        if n < 126:
            head = struct.pack(">BB", 0x80 | op, 0x80 | n)
        elif n < 65536:
            head = struct.pack(">BBH", 0x80 | op, 0x80 | 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | op, 0x80 | 127, n)
        body = bytes(c ^ mask[i & 3] for i, c in enumerate(payload))
        with self.lock:
            self.sock.sendall(head + mask + body)

    def send(self, obj):
        self._send(0x1, json.dumps(obj, separators=(",", ":")).encode())

    def close(self):
        try:
            self._send(0x8, b"")
            self.sock.close()
        except OSError:
            pass


def compact_obs(m):
    s = m.get("self", {})
    return {"tick": m.get("tick"), "t": m.get("t"), "alive": m.get("alive"),
            "self": {k: s.get(k) for k in ("pos", "hp", "max_hp", "energy", "cubes", "aim", "in_zone")},
            "weapons": [w and w.get("kind") for w in s.get("weapons") or []],
            "mechs": [{k: e.get(k) for k in ("id", "kind", "pos", "hp", "aim", "weapons")} for e in m.get("mechs") or []],
            "events": m.get("events"), "zone": m.get("zone"), "drops": m.get("drops")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--map", required=True, help="local arena dir given to the bot as hello.map.dir")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--name", default="test-bot")
    ap.add_argument("--minutes", type=float, default=14.0, help="give up after this long")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("give the bot command after --")
    os.makedirs(a.out, exist_ok=True)

    sid = secrets.token_hex(16)
    req = urllib.request.Request(f"https://{HOST}/mm/code/new?sid={sid}", headers={"User-Agent": UA})
    info = json.loads(urllib.request.urlopen(req, timeout=15).read())
    room, code = info["room"], info["code"]
    base = os.path.join(a.out, f"{time.strftime('%Y%m%d-%H%M%S')}-{code}")
    log("private room", room, "code", code, "->", base)
    ws = WebSocket(f"/r/{room}/play?token=&sid={sid}&name={urllib.parse.quote(a.name)}&code={code}")
    out = open(base + ".bot.jsonl", "w")
    out_lock = threading.Lock()

    def record(kind, m):
        with out_lock:
            out.write(json.dumps({"dir": kind, "at": round(time.time(), 3), "m": m}, separators=(",", ":")) + "\n")

    def spectate():
        try:
            lw = WebSocket(f"/r/{room}/live?token=&code={code}&sid={secrets.token_hex(16)}")
        except (OSError, ConnectionError) as e:
            log("spectator feed unavailable:", e)
            return
        with open(base + ".live.jsonl", "w") as lf:
            while True:
                try:
                    lf.write(lw.recv().rstrip("\n") + "\n")
                except (EOFError, OSError):
                    break

    threading.Thread(target=spectate, daemon=True).start()

    bot = None
    started = False
    sent_at = {}
    lag = []
    bot_ready = threading.Event()

    def relay(proc):
        for raw in proc.stdout:
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if m.get("type") == "ready":
                bot_ready.set()
                continue
            ws.send(m)
            if m.get("tick") in sent_at:
                lag.append(time.perf_counter() - sent_at.pop(m["tick"]))
            record("act", m)

    deadline = time.time() + a.minutes * 60
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except EOFError:
            log("server closed the connection")
            break
        try:
            m = json.loads(raw)
        except ValueError:
            continue
        ty = m.get("type")
        if ty == "lobby":
            you = m.get("you") or {}
            if not you.get("ready"):
                ws.send({"type": "ready", "name": a.name})
            if you.get("host") and m.get("phase") == "waiting" and not started:
                started = True
                time.sleep(1.0)
                ws.send({"type": "start"})
                log("match start requested")
            record("in", m)
        elif ty == "hello":
            m["map"]["dir"] = os.path.abspath(a.map)
            record("in", m)
            bot = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                                   stderr=open(base + ".stderr", "w"))
            threading.Thread(target=relay, args=(bot,), daemon=True).start()
            bot.stdin.write(json.dumps(m) + "\n")
            bot.stdin.flush()
            if not bot_ready.wait(20.0):  # like the scorer: observations start after the bot's `ready`
                log("bot did not send ready within 20 s")
            ws.send({"type": "loaded"})
            log("hello: our slot", m.get("slot"))
        elif ty == "obs":
            record("obs", compact_obs(m))
            if bot and bot.poll() is None:
                sent_at[m.get("tick")] = time.perf_counter()
                try:
                    bot.stdin.write(raw.rstrip("\n") + "\n")
                    bot.stdin.flush()
                except (BrokenPipeError, ValueError):
                    pass
        elif ty == "end":
            record("in", m)
            log("end:", m)
            if bot:
                try:
                    bot.stdin.write(raw.rstrip("\n") + "\n")
                    bot.stdin.close()
                except (BrokenPipeError, ValueError):
                    pass
        elif ty == "results":
            record("in", m)
            log("results received")
            break
        else:
            record("in", m)
    ws.close()
    time.sleep(1.0)
    out.close()
    if bot and bot.poll() is None:
        bot.kill()
    if lag:
        lag.sort()
        log(f"bot answer time (bridge side) p50 {lag[len(lag) // 2] * 1000:.1f} ms  max {lag[-1] * 1000:.1f} ms  n={len(lag)}")


if __name__ == "__main__":
    main()
