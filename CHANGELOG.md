# Changelog

**Sim** = `tools/sim.py`, the rough local stand-in (`NOISE=0.6`), compared on the same seeds.
**Practice** = the real practice server (48 matches), which is ground truth.
"Seeds 200–295" means two 48-match batches: `SEED0=200` and `SEED0=248`.

## v3: fight only mechs that are after us
- **Hostile mechs:** a mech counts as hostile if it damaged the bot in the last 10 s, or has held its aim on the bot for about 0.5 s (hunting it).
  - Targeting, "outnumbered" and cover choice consider only hostiles.
  - Non-hostiles are never attacked: house bots that aren't hunting only fight back once attacked, so attacking them just adds enemies.
  - Lightning fires only when the nearest mech in its cone is the target or hostile, since the arc hits whatever is nearest.
- **Path-search deadline:** path search stops 10 ms into a decision and uses the best partial path. One test's worst decision went from 18 to 11 ms.
- **Sim B** (sim A plus upgrades and supply drops; seeds 200–295): **v2 3.75 → v3 5.36 (+1.61 ± 0.48, 1 SE)**, with 6 matches won and 0.35 drops captured per match. Worst decision 10 ms when run alone; 24 ms only under 4-match load.
- **Sim A** (`DEFEND=1`, seeds 200–295): v2 3.34 → v3 4.15 (+0.80 ± 0.40, 1 SE). The final rule (v4b, below) scored 4.31.
  - Robustness: +1.21 ± 0.39 if idle house bots are passive (`DEFEND=0`); −0.14 ± 0.12 if they shoot on sight (`DEFEND=2`).
- **Tried and dropped** (sim A, 96 matches each):
  - **v4a:** attack a non-hostile only if it's alone, has been watched for 2 s without aiming at the bot, and the bot is above 85% HP. Scored 4.20 (+0.05 vs v3), with fewer early deaths but also fewer kills.
  - **v4b:** never attack non-hostiles. Scored 4.31 (+0.17 vs v3). **Kept**, as the simplest rule.
  - **v5:** wait between fights as far as possible from other mechs. Scored −0.18 vs v4a: hunters arrive later, so fewer kills happen before the 2:00 escalation. **Lesson:** kill fast early.
  - **v6:** duck behind cover while the gun reloads. Scored +0.15 ± 0.30 vs v5, no real effect.

## Sim: upgrades, supply drops, bot timing
- **Upgrades:** the bot now gets real offers (3 random eligible upgrades from `hello.config` each time its cube count passes a threshold; choice 0 after 5 s), and they really change its stats.
- **Cubes:** a cube now heals the max HP it adds.
- **Supply drops** are modelled: called at 70/140/210 s, they land 25 s later inside the next circle; standing alone in the 8 m ring for 4 s gives +3 cubes and full HP and energy. House bots ignore drops.
- **New per-match stats:** `bot_max_ms`, the bot's own worst compute time (read from its debug label, so machine load doesn't affect it), and `drops` captured.

## Sim calibration: house bots fight back (`DEFEND`, now 1 by default)
- **The problem:** in the original sim, house bots that aren't hunting never shoot, even when attacked. The kit's example bot scored 2.19 there, but 1.15 on the real server.
- **New setting:** `DEFEND=0` passive (the old behaviour); `DEFEND=1` shoot back for 8 s after the bot damages them; `DEFEND=2` shoot whenever they see the bot. In every mode, only hunters chase.
- **Example bot under each:** 2.19 / **1.06** / 0.50, against 1.15 real, so `DEFEND=1` became the default.
- **Re-baseline on `DEFEND=1`** (seeds 200–295): v1 3.01, v2 3.34.

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
