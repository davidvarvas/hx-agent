# Changelog

**Sim** = `tools/sim.py`, the rough local stand-in (`NOISE=0.6`), compared on the same seeds.
**Practice** = the real practice server (48 matches), which is ground truth.
"Seeds 200–295" means two 48-match batches: `SEED0=200` and `SEED0=248`.

## v2: loot watchdog, weapon priority
- **Watchdog:** the bot drops any loot or farm target (cube, weapon, crate, NPC drone, supply drop) that hasn't got closer, or lost HP when it's being shot, for 6 s, and leaves it alone for 45 s. Before this, the bot could stand at a wall or shoot an unbreakable crate for minutes (one sim match: 2 minutes at spawn).
- **Weapons first:** while the second weapon slot is empty, a weapon pickup comes before cubes, crates and drones.
- **Weapon memory:** the bot remembers weapon pickups it has seen (they never despawn) and goes back to them, up to 250 m away.
- **Crates:** the bot walks closer while something blocks its shot instead of standing still.
- **Dockerfile:**
  - base image pinned to an exact version and digest (Python 3.13.18, Debian trixie)
  - numpy's math library limited to one thread
  - numpy installed from wheels only
- **`tools/docker_check.sh`:** runs the README's sandbox check and the linux/amd64 build.
- **Sim:** 4.91 → 5.25 (+0.35 over 96 matches, seeds 200–295). Docker check: PASS.
- **Practice:** pending.

## Sim fixes (re-baselined)
- **Bullet hits:** bullets now hit anything along their whole path, using an exact segment-vs-cylinder test. Before, crates were only checked at the end of each 12.6 m bullet step, so most crate hits were lost and the bot could shoot one crate for minutes.
- **Hitbox:** a mech's hitbox now grows with its cubes, as in the real game.
- **New per-match stats:** accuracy, damage dealt and taken, zone damage.

## v1: `30154ab` (initial upload)
- **Sim:** 4.75 (24 matches, old sim). On the fixed sim: 4.85 (seeds 200–247) and 4.96 (248–295).
- **Docker check:** PASS (worst answer 7.1 ms).
- **Practice:** pending.
