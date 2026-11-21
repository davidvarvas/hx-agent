"""Rough local stand-in for the match server, for smoke-testing a bot. NOT the real game.

Runs one bot process (mechfight/1 over stdin/stdout, lockstep) against 15 in-process house bots that
play as a squad and hunt it (1 hunter at start, +1 per kill, all of them after 4:00), like practice.
Models: walking/boost/jump/jet with wall sliding on the 2 m grid, aim slew, gun bullets, lightning,
laser, crates, cubes, weapon pickups, the zone, regen, rear armor, vision with memory, gun sounds, and the
bot's upgrade offers with their real effects from hello.config (house bots get none).
Supply drops are modelled (house bots ignore them). No mortar, no NPC drones. DEFEND (below) sets how
non-hunting house bots react;
DEFEND=1 matched the kit example bot's real practice score (sim 1.06 vs 1.15 real).

    python3 tools/sim.py --seed 3 -- python3 -u bot.py
"""
import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import queue
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import nav  # noqa: E402

NOISE = float(os.environ.get("NOISE", "1"))
# What house bots that are not (yet) hunting do when the bot is around:
# 0 = ignore it completely (original sim), 1 = shoot back for 8 s after the bot damages them,
# 2 = also shoot whenever they can see it (they still only chase when hunting).
DEFEND = int(os.environ.get("DEFEND", "1"))
# FFA=1: the finals' free-for-all instead of practice: every house bot fights the nearest mech it can see
# (other house bots included); no hunting. Use SKILL tiers via --skill to set the field's strength.
FFA = int(os.environ.get("FFA", "0"))
KIT = os.environ.get("MF_KIT", os.path.join(os.path.dirname(os.path.dirname(HERE)), "mechfight-kit"))
TAU = 2 * math.pi


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def seg_cyl(o, e, cx, cy, r, z0, z1):
    """Parameter s in [0, 1] where segment o->e first enters the vertical cylinder (axis (cx, cy), radius r,
    z0..z1), or None."""
    dx, dy, dz = e[0] - o[0], e[1] - o[1], e[2] - o[2]
    fx, fy = o[0] - cx, o[1] - cy
    a = dx * dx + dy * dy
    c = fx * fx + fy * fy - r * r
    if a < 1e-12:
        if c > 0:
            return None
        s1, s2 = 0.0, 1.0
    else:
        b = 2 * (fx * dx + fy * dy)
        disc = b * b - 4 * a * c
        if disc < 0:
            return None
        sq = math.sqrt(disc)
        s1, s2 = (-b - sq) / (2 * a), (-b + sq) / (2 * a)
        if s2 < 0 or s1 > 1:
            return None
        s1, s2 = max(0.0, s1), min(1.0, s2)
    za, zb = o[2] + dz * s1, o[2] + dz * s2
    if z0 <= za <= z1:
        return s1
    if (za > z1 and zb > z1) or (za < z0 and zb < z0):
        return None
    zc = z1 if za > z1 else z0   # enters through the top (or bottom) cap; za != zb so dz != 0
    return (zc - o[2]) / dz


class Mech:
    def __init__(self, i, pos, cfg):
        m = cfg["mech"]
        self.id = i
        self.pos = list(pos)
        self.vel = [0.0, 0.0, 0.0]
        self.aim = [0.0, 0.0]
        self.cmd_aim = [0.0, 0.0]
        self.hp = self.max_hp = float(m["hp"])
        self.energy = float(m["energy"])
        self.spend_t = -9
        self.grounded = True
        self.cubes = 0
        self.alive = True
        self.last_combat = -99
        self.mc = dict(m)  # this mech's [mech] numbers; upgrades change them
        self.wstats = {k: dict(v) for k, v in cfg["weapons"].items()}  # its weapon numbers per kind (upgrades stick)
        self.upg = {}
        self.offers_given = 0
        self.weapons = [{"kind": "gun", "cooldown": 0.0, "ammo": 12, "reload": 0.0, "stats": self.wstats["gun"]}, None]
        self.events = []
        self.seen = {}
        self.kills = 0
        self.charging = False
        self.pending_offers = 0
        self.offer = None


class Sim:
    def __init__(self, seed, cmd, verbose=False, skill=None):
        self.rng = random.Random(seed)
        self.urng = random.Random(seed * 7919 + 17)  # upgrade offers: separate stream, same world per seed
        hello = json.loads(__import__("gzip").open(os.path.join(KIT, "check/stream.jsonl.gz"), "rt").readline())
        self.cfg = hello["config"]
        self.nav = nav.NavMap(os.path.join(KIT, "arena"))
        self.dt = 1.0 / self.cfg["match"]["tick_hz"]
        self.tick = 0
        self.t = 0.0
        self.verbose = verbose
        n = self.nav
        zc = self.cfg["zone"]["start_center"]
        zr = self.cfg["zone"]["start_radius"]
        spawns = []
        while len(spawns) < 16:
            a = self.rng.random() * TAU
            r = math.sqrt(self.rng.random()) * zr * 0.8
            x, y = zc[0] + math.cos(a) * r, zc[1] + math.sin(a) * r
            if not (n.minx + 30 < x < n.minx + n.nx * 2 - 30 and n.miny + 30 < y < n.miny + n.ny * 2 - 30):
                continue
            if not n.is_free(x, y):
                continue
            if all(math.dist((x, y), s) > self.cfg["match"].get("spawn_min_separation", 130) for s in spawns):
                spawns.append((x, y))
        self.me_id = self.rng.randrange(16)
        self.mechs = [Mech(i, (s[0], s[1], n.ground_at(*s)), self.cfg) for i, s in enumerate(spawns)]
        self.skill = {}
        tiers = ["easy"] * 4 + ["medium"] * 4 + ["hard"] * 4 + ["expert"] * 3
        others = [m.id for m in self.mechs if m.id != self.me_id]
        for i, mid in enumerate(others):
            self.skill[mid] = skill or tiers[i]
        self.hunt_order = others[:]  # weakest first
        self.projectiles = []
        self.crates = []
        self.cubes = []
        self.pickups = []
        self.next_id = 1000
        for _ in range(self.cfg["crates"]["count"]):
            p = self._rand_free()
            self.crates.append({"id": self._nid(1000), "pos": [p[0], p[1], n.ground_at(*p)], "hp": 300})
        for _ in range(self.cfg["loot"]["floor_count"]):
            p = self._rand_free()
            self.pickups.append({"id": self._nid(8000), "kind": self.rng.choice(["laser", "lightning"]), "pos": [p[0], p[1], n.ground_at(*p)]})
        self.sounds = {i: [] for i in range(16)}
        self.beams = []
        self.zone_phase = 0
        self.drops = []          # supply drops: called at drops.times, land fall_s later inside the next circle
        self.drops_called = 0
        self.drng = random.Random(seed * 104729 + 3)  # separate stream: same world per seed
        self._zone_setup()
        self.deaths = []  # (t, id)
        self.st = {"shots": 0, "hits": 0, "dealt": 0.0, "taken": 0.0, "zone": 0.0}  # the bot's own match stats
        self.bot = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr if verbose else subprocess.DEVNULL, text=True, bufsize=1)
        self.outq = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        h = dict(hello)
        h["slot"] = self.me_id
        h["seed"] = seed
        h["map"] = {"dir": os.path.join(KIT, "arena"), "files": ["v2/world.json", "v2/terrain.i16"]}
        self._send(h)
        r = self.outq.get(timeout=20)
        assert json.loads(r)["type"] == "ready"
        self.times = []
        self.late = 0
        self.bot_ms = 0
        self.last_action = {}

    def _nid(self, base):
        self.next_id += 1
        return base + self.next_id

    def _rand_free(self):
        zc = self.cfg["zone"]["start_center"]
        while True:
            a = self.rng.random() * TAU
            r = math.sqrt(self.rng.random()) * 450
            x, y = zc[0] + math.cos(a) * r, zc[1] + math.sin(a) * r
            if self.nav.is_free(x, y):
                return (x, y)

    def _reader(self):
        for line in self.bot.stdout:
            self.outq.put(line)
        self.outq.put(None)

    def _send(self, msg):
        try:
            self.bot.stdin.write(json.dumps(msg) + "\n")
            self.bot.stdin.flush()
        except BrokenPipeError:
            pass

    # ------------------------------------------------------------------ zone
    def _zone_setup(self):
        zc = self.cfg["zone"]
        self.zcenter = list(zc["start_center"])
        self.zradius = zc["start_radius"]
        self.phase_t0 = 0.0
        self._next_phase()

    def _next_phase(self):
        phases = self.cfg["zone"]["phases"]
        if self.zone_phase >= len(phases):
            self.znext = None
            return
        ph = phases[self.zone_phase]
        a = self.rng.random() * TAU
        r = self.rng.random() * max(0.0, self.zradius - ph["radius"])
        self.znext = [self.zcenter[0] + math.cos(a) * r, self.zcenter[1] + math.sin(a) * r]
        self.znr = ph["radius"]
        self.ss = self.phase_t0 + ph["hold_s"]
        self.se = self.ss + ph["shrink_s"]
        self.zdps = ph["dps"]

    def zone_now(self):
        if self.znext is None:
            return self.zcenter, self.zradius
        if self.t <= self.ss:
            return self.zcenter, self.zradius
        f = min(1.0, (self.t - self.ss) / (self.se - self.ss))
        c = [self.zcenter[k] + (self.znext[k] - self.zcenter[k]) * f for k in range(2)]
        return c, self.zradius + (self.znr - self.zradius) * f

    def _drops_tick(self):
        dc = self.cfg.get("drops")
        if not dc:
            return
        times = dc.get("times", [])
        if self.drops_called < len(times) and self.t >= times[self.drops_called]:
            self.drops_called += 1
            c = self.znext or self.zcenter
            r = (self.znr if self.znext else self.zradius) * dc.get("spread", 0.7)
            for _ in range(200):  # open ground inside the circle the zone is closing to
                a, rr = self.drng.random() * TAU, math.sqrt(self.drng.random()) * r
                x, y = c[0] + math.cos(a) * rr, c[1] + math.sin(a) * rr
                if self.nav.is_free(x, y):
                    break
            self.drops.append({"id": 20000 + self.drops_called, "pos": [x, y, self.nav.ground_at(x, y)], "radius": dc["radius"],
                               "land_t": self.t + dc["fall_s"], "capture_s": dc["capture_s"], "progress": 0.0, "holder": None})
        for d in list(self.drops):
            if self.t < d["land_t"]:
                continue
            inside = [m for m in self.mechs if m.alive and math.hypot(m.pos[0] - d["pos"][0], m.pos[1] - d["pos"][1]) < d["radius"]
                      and abs(m.pos[2] - d["pos"][2]) < 6]
            if not inside:
                d["holder"], d["progress"] = None, 0.0
            elif len(inside) == 1:
                m = inside[0]
                if d["holder"] != m.id:
                    d["holder"], d["progress"] = m.id, 0.0  # a different sole occupant: the clock restarts
                d["progress"] += self.dt
                if d["progress"] >= d["capture_s"]:
                    self.drops.remove(d)
                    for _ in range(dc.get("cubes", 3)):
                        m.cubes += 1
                        if m.cubes <= self.cfg["cubes"]["stat_cap"]:
                            m.max_hp *= 1 + 0.04 / (1 + 0.04 * (m.cubes - 1))
                    if dc.get("repair", 1):
                        m.hp = m.max_hp
                    m.energy = m.mc["energy"]
                    m.events.append({"type": "drop", "id": d["id"], "cubes": m.cubes})
                    if m.id == self.me_id:
                        self.st["drops"] = self.st.get("drops", 0) + 1
            # two or more in the ring: the clock freezes

    def _zone_tick(self):
        if self.znext is not None and self.t >= self.se:
            self.zcenter, self.zradius = self.znext, self.znr
            self.phase_t0 = self.se
            self.zone_phase += 1
            last_dps = self.zdps
            self._next_phase()
            if self.znext is None:
                self.zdps = last_dps

    # ------------------------------------------------------------------ observation
    def visible(self, m, o):
        dx, dy = o.pos[0] - m.pos[0], o.pos[1] - m.pos[1]
        d = math.hypot(dx, dy)
        v = self.cfg["vision"]
        if d > v["range"]:
            return False
        if d > v["near_range"] and abs(wrap(math.atan2(dy, dx) - m.aim[0])) > math.radians(v["fov_deg"]) / 2:
            return False
        return self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 8), (o.pos[0], o.pos[1], o.pos[2] + 8.5))

    def visible_pt(self, m, p):
        dx, dy = p[0] - m.pos[0], p[1] - m.pos[1]
        d = math.hypot(dx, dy)
        v = self.cfg["vision"]
        if d > v["range"]:
            return False
        if d > v["near_range"] and abs(wrap(math.atan2(dy, dx) - m.aim[0])) > math.radians(v["fov_deg"]) / 2:
            return False
        return self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 8), (p[0], p[1], p[2] + 1))

    def obs_for(self, m):
        mechs = []
        for o in self.mechs:
            if o is m or not o.alive:
                continue
            if self.visible(m, o):
                m.seen[o.id] = self.t
            if self.t - m.seen.get(o.id, -99) <= self.cfg["vision"]["memory_s"]:
                mechs.append({"id": o.id, "kind": "mech", "pos": [round(c, 2) for c in o.pos], "vel": [round(c, 2) for c in o.vel],
                              "aim": o.aim[:], "hp": round(o.hp, 2), "max_hp": o.max_hp, "cubes": o.cubes,
                              "weapons": [w["kind"] for w in o.weapons if w], "charging": o.charging})
        zc, zr = self.zone_now()
        z = {"center": zc, "radius": zr,
             "next_center": self.znext if self.znext else zc, "next_radius": self.znr if self.znext else 0,
             "shrink_start": self.ss, "shrink_end": self.se, "dps": self.zdps}
        st = dict(m.mc)
        st["hp"] = m.max_hp
        o = {"type": "obs", "tick": self.tick, "t": round(self.t, 2), "alive": sum(1 for q in self.mechs if q.alive),
             "self": {"id": m.id, "pos": m.pos[:], "vel": m.vel[:], "aim": m.aim[:], "hp": m.hp, "max_hp": m.max_hp,
                      "energy": m.energy, "max_energy": m.mc["energy"], "grounded": m.grounded, "cubes": m.cubes,
                      "upgrades": [k for k, n in m.upg.items() for _ in range(n)],
                      "in_zone": math.dist(m.pos[:2], zc) <= zr,
                      "weapons": [dict(w) if w else None for w in m.weapons], "stats": st},
             "mechs": mechs,
             "projectiles": [{"id": p["id"], "kind": "gun", "pos": p["pos"], "vel": p["vel"]} for p in self.projectiles
                             if p["by"] != m.id and math.dist(p["pos"], m.pos) < 200],
             "crates": [c for c in self.crates if self.visible_pt(m, c["pos"])],
             "cubes": [c for c in self.cubes if self.visible_pt(m, c["pos"])],
             "pickups": [p for p in self.pickups if self.visible_pt(m, p["pos"])],
             "sounds": self.sounds[m.id], "beams": [], "events": m.events, "zone": z,
             "offer": m.offer,
             "drops": [{"id": d["id"], "pos": d["pos"], "radius": d["radius"], "lands_in": round(max(0.0, d["land_t"] - self.t), 2),
                        "capture_s": d["capture_s"], "progress": round(d["progress"], 2), "holder": d["holder"]} for d in self.drops]}
        return o

    # ------------------------------------------------------------------ actions
    def apply(self, m, a):
        mc = m.mc
        mv = a.get("move", [0, 0])
        l = math.hypot(*mv)
        if l > 1:
            mv = [mv[0] / l, mv[1] / l]
        speed = mc["walk_speed"]
        boost = a.get("boost") and m.energy > 0
        if m.charging:
            speed *= 0.5
        if boost and m.grounded and l > 0.1:
            speed = mc["boost_speed"]
        m.want = (mv[0] * speed, mv[1] * speed)
        m.boost = bool(boost)
        if "aim" in a:
            m.cmd_aim = [a["aim"][0], max(mc["min_pitch"], min(mc["max_pitch"], a["aim"][1]))]
        if a.get("jump") and m.grounded:
            m.vel[2] = mc["jump_speed"]
            m.grounded = False
        m.fire = a.get("fire", [False, False])
        if a.get("reload"):
            g = m.weapons[0]
            if g and g["kind"] == "gun" and g["reload"] == 0 and g["ammo"] < g["stats"]["mag"]:
                g["reload"] = g["stats"]["reload"]
        if "pick" in a and m.offer:
            ch = m.offer["choices"]
            i = a["pick"] if isinstance(a["pick"], int) and 0 <= a["pick"] < len(ch) else 0
            m.offer = None
            self._apply_upgrade(m, ch[i]["id"])
        if "take" in a:
            self._take(m, a["take"], a.get("drop"))

    def _take(self, m, pid, drop):
        p = next((q for q in self.pickups if q["id"] == pid), None)
        if p is None:
            m.events.append({"type": "take_failed", "id": pid, "reason": "gone"}); return
        if math.dist(p["pos"][:2], m.pos[:2]) > self.cfg["loot"]["pickup_radius"]:
            m.events.append({"type": "take_failed", "id": pid, "reason": "range"}); return
        if any(w and w["kind"] == p["kind"] for w in m.weapons):
            m.events.append({"type": "take_failed", "id": pid, "reason": "have"}); return
        slot = 1 if m.weapons[1] is None else (0 if m.weapons[0] is None else drop)
        if slot is None:
            m.events.append({"type": "take_failed", "id": pid, "reason": "full"}); return
        old = m.weapons[slot]
        self.pickups.remove(p)
        k = p["kind"]
        w = {"kind": k, "cooldown": max(self.cfg["loot"].get("equip_s", 1.0), m.wstats[k]["cooldown"]), "stats": m.wstats[k]}
        if k == "laser":
            w["charge"] = 0
        m.weapons[slot] = w
        m.events.append({"type": "took", "id": pid, "kind": k, "slot": slot})
        if old:
            nid = self._nid(8000)
            self.pickups.append({"id": nid, "kind": old["kind"], "pos": m.pos[:]})
            m.events.append({"type": "dropped", "id": nid, "kind": old["kind"], "slot": slot})

    # ------------------------------------------------------------------ physics
    def surface(self, x, y, z):
        n = self.nav
        i, j = n.cell(x, y)
        g = float(n.ground[j, i])
        top = float(n.top[j, i])
        if top > g and top <= z + 1.2:
            return top, False
        if top > g + 1.2 and n.base[j, i] < z + 9:
            return g, True  # wall
        if n.blocked[j, i] and top <= g:
            return g, z < g + 1.0 and False
        return g, False

    def move(self, m):
        mc = m.mc
        dt = self.dt
        acc = mc["ground_accel"] if m.grounded else mc["air_accel"]
        for k in range(2):
            dv = m.want[k] - m.vel[k]
            lim = acc * dt
            m.vel[k] += max(-lim, min(lim, dv))
        if m.boost and not m.grounded and m.energy > 0:
            m.vel[2] = min(mc["max_rise_speed"], m.vel[2] + mc["jet_accel"] * dt)
            m.energy -= mc["jet_drain"] * dt
            m.spend_t = self.t
        elif m.boost and m.grounded and math.hypot(*m.want) > 1:
            m.energy -= mc["boost_drain"] * dt
            m.spend_t = self.t
        m.energy = max(0.0, m.energy)
        if self.t - m.spend_t > mc["energy_regen_delay"]:
            m.energy = min(mc["energy"], m.energy + mc["energy_regen"] * dt)
        m.vel[2] -= mc["gravity"] * dt
        x, y, z = m.pos
        nx, ny = x + m.vel[0] * dt, y + m.vel[1] * dt
        r = 2.5

        def blocked(px, py):
            for ox, oy in ((r, 0), (-r, 0), (0, r), (0, -r), (0, 0)):
                s, wall = self.surface(px + ox, py + oy, z)
                if wall or s > z + 1.2:
                    return True
            return not (self.nav.minx + 3 < px < self.nav.minx + self.nav.nx * 2 - 3 and self.nav.miny + 3 < py < self.nav.miny + self.nav.ny * 2 - 3)
        if blocked(nx, ny):
            if not blocked(nx, y):
                ny = y; m.vel[1] = 0
            elif not blocked(x, ny):
                nx = x; m.vel[0] = 0
            else:
                nx, ny = x, y; m.vel[0] = m.vel[1] = 0
        nz = z + m.vel[2] * dt
        s, _ = self.surface(nx, ny, z)
        if nz <= s:
            nz = s
            m.vel[2] = 0
            m.grounded = True
        else:
            m.grounded = nz <= s + 0.05
        m.pos = [nx, ny, nz]
        # aim slew
        ty = wrap(m.cmd_aim[0] - m.aim[0])
        step = mc["turn_rate"] * dt
        m.aim[0] = wrap(m.aim[0] + max(-step, min(step, ty)))
        tp = m.cmd_aim[1] - m.aim[1]
        step = mc["pitch_rate"] * dt
        m.aim[1] += max(-step, min(step, tp))

    # ------------------------------------------------------------------ weapons
    def aim_vec(self, m):
        y, p = m.aim
        return (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))

    def fire(self, m):
        for i, w in enumerate(m.weapons):
            if not w:
                continue
            w["cooldown"] = max(0.0, w["cooldown"] - self.dt)
            trig = m.fire[i] if i < len(m.fire) else False
            k = w["kind"]
            s = w["stats"]
            if k == "gun":
                if w["reload"] > 0:
                    w["reload"] = max(0.0, w["reload"] - self.dt)
                    if w["reload"] == 0:
                        w["ammo"] = s["mag"]
                    continue
                if trig and w["cooldown"] <= 0 and w["ammo"] > 0:
                    w["cooldown"] = s["cooldown"]
                    w["ammo"] -= 1
                    if w["ammo"] == 0:
                        w["reload"] = s["reload"]
                    sp = math.radians(s["spread_deg"])
                    yy = m.aim[0] + self.rng.gauss(0, sp)
                    pp = m.aim[1] + self.rng.gauss(0, sp)
                    d = (math.cos(pp) * math.cos(yy), math.cos(pp) * math.sin(yy), math.sin(pp))
                    o = [m.pos[0] + d[0] * 3, m.pos[1] + d[1] * 3, m.pos[2] + 7 + d[2] * 3]
                    self.projectiles.append({"id": self._nid(0), "by": m.id, "pos": o, "vel": [d[k2] * s["speed"] for k2 in range(3)],
                                             "left": s["range"], "dmg": s["damage"] * (1 + 0.04 * min(m.cubes, 10))})
                    self._sound(m, "gun")
                    m.last_combat = self.t
                    if m.id == self.me_id:
                        self.st["shots"] += 1
            elif k == "lightning":
                if trig and w["cooldown"] <= 0 and m.energy >= s["energy"]:
                    w["cooldown"] = s["cooldown"]
                    m.energy -= s["energy"]
                    m.spend_t = self.t
                    self._sound(m, "lightning")
                    best = None
                    for o in self._targets(m):
                        d = math.dist(o["pos"][:2], m.pos[:2])
                        b = math.atan2(o["pos"][1] - m.pos[1], o["pos"][0] - m.pos[0])
                        if d < s["range"] and abs(wrap(b - m.aim[0])) < math.radians(s["cone_deg"]) / 2:
                            if self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 7), (o["pos"][0], o["pos"][1], o["pos"][2] + 2)):
                                if best is None or d < best[0]:
                                    best = (d, o)
                    if best:
                        self._damage(m, best[1], s["damage"] * (1 + 0.04 * min(m.cubes, 10)), "lightning", m.pos)
            elif k == "laser":
                if w["cooldown"] > 0:
                    m.charging = False
                    continue
                if trig:
                    w["charge"] = w.get("charge", 0) + self.dt
                    m.charging = True
                    if w["charge"] >= s["charge"] + s["hold_s"]:
                        trig = False
                if not trig and w.get("charge", 0) > 0:
                    frac = s["min_frac"] + (1 - s["min_frac"]) * min(1.0, w["charge"] / s["charge"])
                    w["charge"] = 0
                    m.charging = False
                    w["cooldown"] = s["cooldown"]
                    self._sound(m, "laser")
                    self._hitscan(m, s["range"], s["damage"] * frac * (1 + 0.04 * min(m.cubes, 10)))

    def _targets(self, m):
        out = []
        for o in self.mechs:
            if o is not m and o.alive:
                out.append({"obj": o, "pos": o.pos, "r": 2.5, "h": 9})
        for c in self.crates:
            out.append({"obj": c, "pos": c["pos"], "r": 1.4, "h": 2.4})
        return out

    def _hitscan(self, m, rng, dmg):
        d = self.aim_vec(m)
        o = (m.pos[0], m.pos[1], m.pos[2] + 7)
        best = None
        for t in self._targets(m):
            p = t["pos"]
            # closest approach of ray to cylinder axis (2D)
            rx, ry = p[0] - o[0], p[1] - o[1]
            h = math.hypot(d[0], d[1]) or 1e-6
            s = (rx * d[0] + ry * d[1]) / (h * h)
            if s < 0 or s * h > rng:
                continue
            cx, cy = o[0] + d[0] * s, o[1] + d[1] * s
            if math.hypot(cx - p[0], cy - p[1]) > t["r"]:
                continue
            cz = o[2] + d[2] * s
            if not (p[2] <= cz <= p[2] + t["h"]):
                continue
            if best is None or s < best[0]:
                best = (s, t)
        if best:
            s, t = best
            end = (o[0] + d[0] * s, o[1] + d[1] * s, o[2] + d[2] * s)
            if self.nav.los(o, end):
                self._damage(m, t, dmg, "laser", m.pos)

    def _sound(self, m, kind):
        rng = self.cfg["sound"]["range"][kind]
        for o in self.mechs:
            if o is m or not o.alive:
                continue
            d = math.dist(o.pos[:2], m.pos[:2])
            if d < rng:
                b = math.atan2(m.pos[1] - o.pos[1], m.pos[0] - o.pos[0]) + self.rng.gauss(0, math.radians(7))
                self.sounds[o.id].append({"kind": kind, "bearing": b, "dist": "near" if d < 60 else "mid" if d < 160 else "far", "age": 0.05})

    def _damage(self, src, t, dmg, weapon, origin):
        obj = t["obj"] if isinstance(t, dict) and "obj" in t else t
        if isinstance(obj, Mech):
            if not obj.alive:
                return
            b = math.atan2(origin[1] - obj.pos[1], origin[0] - obj.pos[0])
            rear = abs(wrap(b - obj.aim[0])) > math.pi / 2
            if rear:
                dmg *= 1.5
            dmg *= max(0.0, 1.0 - obj.mc.get("armor", 0.0))  # armor: weapon damage only (zone damage is applied elsewhere)
            if src is not None and src.id == self.me_id:
                self.st["dealt"] += dmg
                obj.hit_by_me = self.t
                if weapon == "gun":
                    self.st["hits"] += 1
            if src is not None:
                obj.hurt_by, obj.hurt_t = src.id, self.t
            if obj.id == self.me_id:
                self.st["taken"] += dmg
            obj.hp -= dmg
            obj.last_combat = self.t
            obj.events.append({"type": "damaged", "amount": round(dmg, 2), "weapon": weapon, "bearing": b, "by": src.id if src else None, "rear": rear})
            if src:
                src.events.append({"type": "hit", "target": obj.id, "amount": round(dmg, 2), "weapon": weapon})
                src.last_combat = self.t
            if obj.hp <= 0:
                self._kill(obj, src)
        else:
            obj["hp"] -= dmg
            if src is not None and src.id == self.me_id and weapon == "gun":
                self.st["hits"] += 1  # crate hits count toward accuracy too
            if src:
                src.events.append({"type": "hit", "target": obj["id"], "amount": dmg, "weapon": weapon})
            if obj["hp"] <= 0 and obj in self.crates:
                self.crates.remove(obj)
                self.cubes.append({"id": self._nid(5000), "pos": obj["pos"][:]})
                if self.rng.random() < 0.5:
                    self.pickups.append({"id": self._nid(8000), "kind": self.rng.choice(["laser", "lightning"]), "pos": obj["pos"][:]})

    def _kill(self, m, src):
        m.alive = False
        self.deaths.append((self.tick, m.id))
        for k in range(m.cubes + 2):
            a = k * 1.3
            self.cubes.append({"id": self._nid(5000), "pos": [m.pos[0] + math.cos(a) * 2, m.pos[1] + math.sin(a) * 2, m.pos[2]]})
        for w in m.weapons:
            if w and w["kind"] != "gun":
                self.pickups.append({"id": self._nid(8000), "kind": w["kind"], "pos": m.pos[:]})
        if src:
            src.kills += 1
            src.events.append({"type": "kill", "target": m.id})
        for o in self.mechs:
            if o.alive and math.dist(o.pos, m.pos) < 600:
                self.sounds[o.id].append({"kind": "death", "bearing": math.atan2(m.pos[1] - o.pos[1], m.pos[0] - o.pos[0]), "dist": "far", "age": 0.05})

    def step_projectiles(self):
        keep = []
        pr = self.cfg.get("projectile", {}).get("gun_radius", 0.3)
        cr = self.cfg["crates"].get("radius", 1.4) + pr
        ch = self.cfg["crates"].get("height", 2.4)
        for p in self.projectiles:
            o = p["pos"]
            dist = math.hypot(*p["vel"]) * self.dt
            e = [o[k] + p["vel"][k] * self.dt for k in range(3)]
            # first thing the segment o->e enters: a mech or a crate (exact segment-vs-cylinder)
            hit = None
            for m in self.mechs:
                if not m.alive or m.id == p["by"]:
                    continue
                sc = 1 + 0.05 * m.cubes
                s = seg_cyl(o, e, m.pos[0], m.pos[1], 2.5 * sc + pr, m.pos[2], m.pos[2] + 9 * sc)
                if s is not None and (hit is None or s < hit[0]):
                    hit = (s, m)
            for c in self.crates:
                s = seg_cyl(o, e, c["pos"][0], c["pos"][1], cr, c["pos"][2], c["pos"][2] + ch)
                if s is not None and (hit is None or s < hit[0]):
                    hit = (s, {"obj": c})
            if not self.nav.los(o, e if not hit else [o[k] + (e[k] - o[k]) * hit[0] for k in range(3)]):
                continue
            if hit:
                self._damage(self.mechs[p["by"]], hit[1], p["dmg"], "gun", o)
                continue
            p["left"] -= dist
            p["pos"] = e
            if p["left"] > 0:
                keep.append(p)
        self.projectiles = keep

    # ------------------------------------------------------------------ house bots
    def house(self, m):
        if FFA:
            return self._house_ffa(m)
        me = self.mechs[self.me_id]
        sk = self.skill[m.id]
        noise = {"easy": 1.6, "medium": 1.1, "hard": 0.7, "expert": 0.4}[sk] * NOISE
        lead = sk != "easy"
        kills = me.kills
        nh = 1 + kills + (15 if self.t > 240 else 0) + (2 if self.t > 120 else 0)
        hunting = m.id in self.hunt_order[:nh] and me.alive
        zc, zr = self.zone_now()
        nc = self.znext or zc
        a = {"move": [0, 0], "fire": [False, False]}
        defend = False
        if not hunting and me.alive and DEFEND:
            d = math.dist(me.pos[:2], m.pos[:2])
            if d < 200 and (self.t - getattr(m, "hit_by_me", -99) < 8 or DEFEND >= 2):
                defend = self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 8), (me.pos[0], me.pos[1], me.pos[2] + 5))
        if defend:
            a = self._zone_walk(m, zc, nc)  # keeps walking with the zone, and shoots back below
        if hunting or defend:
            d = math.dist(me.pos[:2], m.pos[:2])
            dx, dy = me.pos[0] - m.pos[0], me.pos[1] - m.pos[1]
            ux, uy = dx / max(d, 1e-6), dy / max(d, 1e-6)
            if not hunting:
                pass
            elif d > 55 or not self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 8), (me.pos[0], me.pos[1], me.pos[2] + 5)):
                path = getattr(m, "path", None)
                if path is None or self.t - getattr(m, "path_t", -9) > 2:
                    m.path = self.nav.astar(m.pos[:2], me.pos[:2], max_expand=2500) or []
                    m.path_t = self.t
                while m.path and math.dist(m.path[0], m.pos[:2]) < 4:
                    m.path.pop(0)
                tgt = m.path[0] if m.path else me.pos[:2]
                vx, vy = tgt[0] - m.pos[0], tgt[1] - m.pos[1]
                l = math.hypot(vx, vy) or 1
                a["move"] = [vx / l, vy / l]
            else:
                s = 1 if int(self.t / 1.3 + m.id) % 2 else -1
                a["move"] = [-uy * s, ux * s]
            if self.t - getattr(m, "react", -9) > {"easy": 0.6, "medium": 0.4, "hard": 0.25, "expert": 0.15}[sk]:
                m.react = self.t
                tx, ty, tz = me.pos[0], me.pos[1], me.pos[2] + 4.5
                if lead:
                    tt = d / 252
                    tx += me.vel[0] * tt
                    ty += me.vel[1] * tt
                m.goal_aim = [math.atan2(ty - m.pos[1], tx - m.pos[0]) + self.rng.gauss(0, math.radians(noise)),
                              math.atan2(tz - m.pos[2] - 7, d) + self.rng.gauss(0, math.radians(noise))]
            if hasattr(m, "goal_aim"):
                a["aim"] = m.goal_aim
                if d < 200 and self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 7), (me.pos[0], me.pos[1], me.pos[2] + 4.5)):
                    a["fire"] = [abs(wrap(m.aim[0] - m.goal_aim[0])) < 0.08, False]
        else:
            a = self._zone_walk(m, zc, nc)
        return a

    # ------------------------------------------------------------------ upgrades (the bot's own)
    def _offers(self, m):
        """Offer 3 random eligible upgrades each time the cube count passes a threshold; choice 0 on timeout."""
        if m.offer is not None:
            if self.t >= m.offer["expires"]:
                ch = m.offer["choices"]
                m.offer = None
                self._apply_upgrade(m, ch[0]["id"])
            return
        due = sum(1 for c in self.cfg["cubes"]["upgrade_thresholds"] if m.cubes >= c)
        if m.offers_given >= due:
            return
        held = {w["kind"] for w in m.weapons if w}
        elig = [u for u in self.cfg.get("upgrades", []) if m.upg.get(u["id"], 0) < u.get("max", 1)
                and (u.get("requires") is None or u["requires"] in held)]
        if not elig:
            return
        m.offers_given += 1
        ch = self.urng.sample(elig, min(3, len(elig)))
        m.offer = {"id": m.offers_given, "expires": round(self.t + self.cfg["bot"]["offer_timeout_s"], 2),
                   "choices": [{"id": u["id"], "name": u["name"], "desc": u["desc"]} for u in ch]}

    def _apply_upgrade(self, m, uid):
        u = next((u for u in self.cfg.get("upgrades", []) if u["id"] == uid), None)
        if u is None:
            return
        m.upg[uid] = m.upg.get(uid, 0) + 1
        for ef in u.get("effects", []):
            p = ef["path"].split(".")
            if p[0] == "mech" and len(p) == 2:
                d, key = m.mc, p[1]
            elif p[0] == "weapons" and len(p) == 3 and p[1] in m.wstats:
                d, key = m.wstats[p[1]], p[2]
            else:
                continue
            old = float(d.get(key, 0.0))
            new = old * ef["mul"] if "mul" in ef else old + ef.get("add", 0.0)
            d[key] = new
            if p == ["mech", "hp"] and old > 0:  # plating: more max HP, healing the difference
                gain = m.max_hp * (new / old - 1.0)
                m.max_hp += gain
                m.hp += gain
        m.events.append({"type": "upgrade", "id": uid})

    def _house_ffa(self, m):
        """Free-for-all house bot (FFA=1): fights the nearest mech it can see within 150 m (whoever hit it in
        the last 5 s first), walks with the zone otherwise, and gets back into the zone before fighting on."""
        sk = self.skill[m.id]
        noise = {"easy": 1.6, "medium": 1.1, "hard": 0.7, "expert": 0.4}[sk] * NOISE
        zc, zr = self.zone_now()
        nc = self.znext or zc
        eye = lambda q: (q.pos[0], q.pos[1], q.pos[2] + 8)
        if self.t - getattr(m, "tgt_t", -9) > 1.0 or getattr(m, "tgt", None) is None or not m.tgt.alive:
            m.tgt_t = self.t
            best = None
            for o in self.mechs:
                if o is m or not o.alive:
                    continue
                d = math.dist(o.pos[:2], m.pos[:2])
                if d > 150 or not self.nav.los(eye(m), eye(o)):
                    continue
                s = d - (100 if getattr(m, "hurt_by", None) == o.id and self.t - getattr(m, "hurt_t", -9) < 5 else 0)
                if best is None or s < best[0]:
                    best = (s, o)
            m.tgt = best[1] if best else None
        o = m.tgt
        a = self._zone_walk(m, zc, nc)
        if o is None or not o.alive:
            return a
        d = math.dist(o.pos[:2], m.pos[:2])
        outside = math.dist(m.pos[:2], zc) > zr - 15
        los = self.nav.los(eye(m), (o.pos[0], o.pos[1], o.pos[2] + 5))
        if not outside:
            if d > 55 or not los:
                if getattr(m, "fpath_t", -9) < self.t - 2:
                    m.fpath = self.nav.astar(m.pos[:2], o.pos[:2], max_expand=2500) or []
                    m.fpath_t = self.t
                while m.fpath and math.dist(m.fpath[0], m.pos[:2]) < 4:
                    m.fpath.pop(0)
                tgt = m.fpath[0] if m.fpath else o.pos[:2]
                vx, vy = tgt[0] - m.pos[0], tgt[1] - m.pos[1]
                l = math.hypot(vx, vy) or 1
                a["move"] = [vx / l, vy / l]
            else:
                ux, uy = (o.pos[0] - m.pos[0]) / max(d, 1e-6), (o.pos[1] - m.pos[1]) / max(d, 1e-6)
                s = 1 if int(self.t / 1.3 + m.id) % 2 else -1
                a["move"] = [-uy * s, ux * s]
        if self.t - getattr(m, "react", -9) > {"easy": 0.6, "medium": 0.4, "hard": 0.25, "expert": 0.15}[sk]:
            m.react = self.t
            tx, ty, tz = o.pos[0], o.pos[1], o.pos[2] + 4.5
            if sk != "easy":
                tt = d / 252
                tx += o.vel[0] * tt
                ty += o.vel[1] * tt
            m.goal_aim = [math.atan2(ty - m.pos[1], tx - m.pos[0]) + self.rng.gauss(0, math.radians(noise)),
                          math.atan2(tz - m.pos[2] - 7, max(d, 1.0)) + self.rng.gauss(0, math.radians(noise))]
        if hasattr(m, "goal_aim"):
            a["aim"] = m.goal_aim
            if d < 200 and self.nav.los((m.pos[0], m.pos[1], m.pos[2] + 7), (o.pos[0], o.pos[1], o.pos[2] + 4.5)):
                a["fire"] = [abs(wrap(m.aim[0] - m.goal_aim[0])) < 0.08, False]
        return a

    def _zone_walk(self, m, zc, nc):
        a = {"move": [0, 0], "fire": [False, False]}
        if math.dist(m.pos[:2], nc) > self.znr * 0.6 if self.znext else math.dist(m.pos[:2], zc) > 5:
            path = getattr(m, "path", None)
            if path is None or self.t - getattr(m, "path_t", -9) > 4:
                m.path = self.nav.astar(m.pos[:2], nc, max_expand=2500) or []
                m.path_t = self.t
            while m.path and math.dist(m.path[0], m.pos[:2]) < 4:
                m.path.pop(0)
            tgt = m.path[0] if m.path else nc
            vx, vy = tgt[0] - m.pos[0], tgt[1] - m.pos[1]
            l = math.hypot(vx, vy) or 1
            a["move"] = [vx / l * 0.7, vy / l * 0.7]
        return a

    # ------------------------------------------------------------------ loop
    def run(self, max_t=480):
        me = self.mechs[self.me_id]
        while self.t < max_t:
            alive = [m for m in self.mechs if m.alive]
            if len(alive) <= 1 or not me.alive:
                break
            obs = self.obs_for(me)
            me.events = []
            self.sounds[me.id] = []
            t0 = time.perf_counter()
            self._send(obs)
            act = None
            deadline = t0 + 0.05
            while True:
                try:
                    line = self.outq.get(timeout=max(0.0005, deadline - time.perf_counter()))
                except queue.Empty:
                    break
                if line is None:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("tick") == self.tick:
                    act = msg
                    break
            dtm = time.perf_counter() - t0
            self.times.append(dtm)
            dbg = act.get("debug") if act else None
            if isinstance(dbg, dict):  # our bot reports its own compute time at the end of its label ("... 3ms")
                mm = re.search(r"(\d+)ms$", str(dbg.get("label", "")))
                if mm:
                    self.bot_ms = max(self.bot_ms, int(mm.group(1)))
            if act is None:
                self.late += 1
                act = {k: v for k, v in self.last_action.items() if k in ("move", "aim", "boost")}
            self.last_action = act
            self.apply(me, act)
            for m in alive:
                if m is not me:
                    m.events = []
                    self.sounds[m.id] = []
                    self.apply(m, self.house(m))
            self._offers(me)
            for _ in range(self.cfg["match"]["decide_every"]):
                self.t += self.dt
                for m in self.mechs:
                    if m.alive:
                        self.move(m)
                        self.fire(m)
                self.step_projectiles()
                zc, zr = self.zone_now()
                for m in self.mechs:
                    if not m.alive:
                        continue
                    if math.dist(m.pos[:2], zc) > zr:
                        m.hp -= self.zdps * self.dt
                        m.last_combat = self.t
                        if m is me:
                            self.st["zone"] += self.zdps * self.dt
                        if m is me and self.tick % 20 == 0:
                            m.events.append({"type": "damaged", "amount": self.zdps, "weapon": "zone", "bearing": None, "by": None})
                        if m.hp <= 0:
                            self._kill(m, None)
                    elif self.t - m.last_combat > m.mc["regen_delay"] and m.hp < m.max_hp:
                        m.hp = min(m.max_hp, m.hp + m.mc["regen_per_s"] * self.dt)
                for c in list(self.cubes):
                    best = None
                    for m in self.mechs:
                        if m.alive and math.hypot(m.pos[0] - c["pos"][0], m.pos[1] - c["pos"][1]) < 3.5 and abs(m.pos[2] - c["pos"][2]) < 4:
                            best = m
                            break
                    if best:
                        self.cubes.remove(c)
                        best.cubes += 1
                        old_max = best.max_hp
                        best.max_hp *= 1 + 0.04 / (1 + 0.04 * (best.cubes - 1)) if best.cubes <= 10 else 1
                        best.hp += best.max_hp - old_max  # +4% max HP, healing the difference
                        best.events.append({"type": "pickup", "cubes": best.cubes})
                self.tick += 1
                self._zone_tick()
                self._drops_tick()
            if self.verbose and self.tick % 200 == 0:
                print(f"t={self.t:5.1f} hp={me.hp:6.0f} pos=({me.pos[0]:.0f},{me.pos[1]:.0f}) in_zone={math.dist(me.pos[:2], self.zone_now()[0]) <= self.zone_now()[1]} kills={me.kills} cubes={me.cubes} w={[w['kind'] for w in me.weapons if w]} alive={sum(m.alive for m in self.mechs)}", file=sys.stderr)
        # placement
        if me.alive:
            place = 1 + sum(1 for m in self.mechs if m.alive and m is not me and m.hp > me.hp)
        else:
            dtick = next(tk for tk, i in self.deaths if i == me.id)
            place = sum(1 for m in self.mechs if m.alive) + sum(1 for tk, i in self.deaths if tk >= dtick)
        self._send({"type": "end", "place": place, "kills": me.kills})
        try:
            self.bot.stdin.close()
            self.bot.wait(timeout=3)
        except Exception:
            self.bot.kill()
        cause = "alive" if me.alive else ("zone" if math.dist(me.pos[:2], self.zone_now()[0]) > self.zone_now()[1] else "killed")
        ts = sorted(self.times)
        return {"place": place, "points": 16 - place, "kills": me.kills, "t": round(self.t, 1), "cause": cause,
                "cubes": me.cubes, "weapons": [w["kind"] for w in me.weapons if w],
                "p50ms": round(ts[len(ts) // 2] * 1000, 2), "maxms": round(ts[-1] * 1000, 1), "late": self.late,
                "shots": self.st["shots"], "acc": round(self.st["hits"] / max(1, self.st["shots"]), 3),
                "dealt": round(self.st["dealt"]), "taken": round(self.st["taken"]), "zone_dmg": round(self.st["zone"]),
                "upg": me.upg, "botms": self.bot_ms, "drops": self.st.get("drops", 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--skill", default=os.environ.get("SKILL"))  # easy|medium|hard|expert for every house bot
    ap.add_argument("-v", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    s = Sim(a.seed, cmd, a.v, a.skill)
    print(json.dumps(s.run()))


if __name__ == "__main__":
    main()
