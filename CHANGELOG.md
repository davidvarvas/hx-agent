# Changelog

**Sim** = `tools/sim.py`, the rough local stand-in (`NOISE=0.6`), compared on the same seeds.
**Practice** = the real practice server (48 matches), which is ground truth.
"Seeds 200–295" means two 48-match batches: `SEED0=200` and `SEED0=248`.

## B0: build on the top public entry (attributed)
- **Base:** `bot.py` is now [mech-royale by LanceHuang245](https://github.com/LanceHuang245/mech-royale) at commit `171bc06` (MIT License, Copyright (c) 2026 LanceHuang245).
  - The full license notice is in `third_party/LanceHuang245-mech-royale-LICENSE`, and a credit header is at the top of `bot.py`.
  - In this exact configuration, with no strategy switches (`MR_FLAGS` empty), it scored **4.75** in practice, as recorded by BackwardsDeployeds, who submit the same code.
- **Our only changes:** the strategy-switch default is now empty (the 4.75 setup), and the Dockerfile uses our digest-pinned base and copies only `bot.py` and the kit's `mechfight.py` (standard library only, no numpy).
- **Earlier work:** our own bots (`86aaa4e`, L1, A1, A2) remain in history. The scorer judges which line we continue.
- **Docker check:** PASS (worst answer 7.9 ms).

## Real scorer only from here
- **L1 (`9b5aa78`): practice 3.58.** The sim had said 5.31 vs 3.77. My sims have now mis-ranked my tactics twice, and other teams report the same, so changes are judged only by real practice scores from now on: one change set per submission on the best real bot.
- **A1:** `89ec1cd` plus never-mortar, plating → armor → nanites, and focus fire (stay on the current target).
- **A2:** `89ec1cd` plus three changes, modelled on the 4.75 team's largest real gain (3.71 → 4.44):
  - finish off clear targets under 30% HP, overriding retreat and outnumbered
  - grab cubes within 70 m before fighting
  - dodge gun rounds about to hit

## v7 (L1): new decision core on the GPT bot
- **Base:** `davidvarvas/mech-royale-bot-gpt` `89ec1cd` (4.08 real), the team's best scored bot. Its aiming, supply-drop, combat-loot and final-centre code are kept.
- **Sources:** my own implementation of design principles learned by reading public entries; no code was copied:
  - `LanceHuang245/mech-royale` (MIT; 4.75 real): README and code read for structure
  - `nullat0m7/mech-royale`: changelog
  - BingBU: README
- **Situation:** incoming damage per second (last 2.5 s); hits from attackers out of sight; threats in view within 240 m; a retreat latch (below 38% HP until 80%, or 60% after 12 s without damage).
- **Mode order:**
  1. final centre
  2. zone edge
  3. cover when retreating, outnumbered (3+ threats, 2+ under 60% HP, more than 110 damage per second, or an unseen attacker) or out-ranged by a laser, unless the fight is close or a kill is near
  4. zone rotation
  5. supply drop
  6. fight any target with a clear shot
  7. farm and roam
  - The bot keeps firing while it repositions.
- **Targeting:** distance + 0.2 × HP, −100 under 30% HP, +400 without a clear shot, −120 for the current target, −40 for whoever just hit us.
- **Cover:** 16 rays out to 75 m (stopping at walls); score = 100 × threats that can see the spot + 0.8 × distance − 12 × (alignment with "away from the threats"). A fully hidden spot is held.
- **Combat range:**
  - laser 110 m
  - lightning 28 m
  - gun only 85 m
  - laser and lightning: 28 m when the target is closer than 60 m
  - finishing: 28 m (55 m without lightning)
  - It strafes in longer runs.
- **Other changes:**
  - it turns to face unseen attackers
  - it dodges bullets that are about to hit
  - loadout is laser plus lightning (the gun is dropped for the second), never a mortar
  - upgrades: plating, armor, nanites first
  - it shoots crates out to 150 m and returns to crates it saw earlier
  - it boosts to far loot when no mech is within 80 m
  - farming has a stall watchdog
- **Sim F** (armed house bots, mortar pickups, upgrades, drops; 96 matches): GPT `89ec1cd` 3.77 → **5.31 (+1.54 ± 0.49)**.
  - Alive at the end in 12 of 96 matches (was 2); 4.6 kills (was 3.2).
  - Weakness: 31 of 96 die in the first minute; it fights anything it sees before it is armed.
- **Also tried on sim F:**
  - g1 (no mortars, plating/armor/nanites order, focus fire): 3.84 (+0.07)
  - g2 (g1 plus crate farming to 160 m in the first 2 minutes): 3.78, only +0.2 cubes
- **Sim F** adds mortar pickups (`loot.weights`) and the laser cook-off (+60% to a mech carrying a mortar). Practice: pending.

## Real result and sim E (armed house bots)
- **Practice for `86aaa4e`: 3.60.** That's below the prediction (3.9) and below the GPT bot's best (4.08). The GPT bot's four practice runs averaged 3.92 (3.79–4.08), so one run's noise is about ±0.3.
- **Sim E (`ARMED=1`, now the default):** house bots pick up weapons and use lasers and lightning, as the real ones did in live matches. Calibration, 96 matches each:

  | Bot | Sim E | Real practice |
  | --- | ---: | ---: |
  | Kit example bot | 0.78 | 1.15 |
  | GPT `89ec1cd` | 3.33 | 4.08 (3.92 average) |
  | this repo `86aaa4e` | 3.38 | 3.60 |

- **What sim E shows:**
  - Sim E is in the real range, about 0.4 too pessimistic. The earlier sims were about 1.6× too optimistic.
  - It rates the two bots about equal, consistent with the real gap being mostly noise.
  - Damage taken: guns 61%, lasers 25%, lightning 14%. Most deaths happen at 120–180 s, when this sim adds two hunters.

## Research: public entries and live matches
Other teams' repos are public by rule. I read their READMEs for ideas only; no code was copied. Ideas tried here:
- **Fight at long range (BingBU, 4.15):** its README says the weaker house bots stop hitting at about 145 m.
- **Avoid drone farming (Edgewise):** it argues placement matters more than cubes.
- **Free-for-all detection (BingBU):** from deaths the bot didn't cause, the same idea as v5 here.
- **The public play server (two teams' tools):** a private room fills the empty seats with the server's own bots. `tools/live.py` here is our own connector.

**Live matches** (play server, private rooms; these are free-for-alls with the competition rules at 2× speed):
- **House bots:** expert, red, crimson, skirmish and astra types. They loot, and lasers are common.
- **`86aaa4e`:** 1st (5 kills), 4th (2 kills).
- **Long-range variant** (gun duels at about 140 m): 4th, then 7th. In the 7th-place match, drones farmed at 55–85 m did 900 damage.
- **Damage by distance** (2 matches): 98% of house-bot gun damage on us landed within 80 m, while about half their laser damage came from 80–120 m.

## Tried and dropped: drone farming from beyond their chase range, duel range by loadout
- **Drones:** farm from 95–125 m, beyond the drone's give-up distance (`npc.deaggro_range` + 5 m), instead of 55–85 m.
- **Duel range by the target's visible loadout:**
  - gun only: about 95 m (gun fire allowed up to 150 m)
  - laser or mortar: 60 m
  - lightning: 85 m
  - when we have lightning: close in to 26 m
- **Results:**
  - Sim D: 6.24 (+0.18 ± 0.32), no difference.
  - Live: 6th place, 0 kills. An expert with lightning killed it at close range, and 353 damage came from behind.
- **Live record so far:** `86aaa4e` placed 1st and 4th, the long-range variant 4th and 7th, and this one 6th. There's no evidence either range change helps, so I dropped it.
- **Drone damage:** by the rules, farming one drone from 55–85 m costs only about 75 HP, so the 900 drone damage was more likely the long-range variant drifting into drone territory.

## Calibration against real practice scores (sim D, 96 matches each)
| Bot | Sim | Real practice |
| --- | ---: | ---: |
| Kit example bot | 1.33 | 1.15 |
| `mech-royale-bot-gpt` `89ec1cd` | 6.27 | 4.08 |
| `mech-royale-bot-gpt` `0003b87` | 6.11 | 3.79 |
| this repo `86aaa4e` (v5) | 6.06 | predicted ≈ 3.9 |

- **Fit:** real ≈ 0.38 + 0.57 × sim. At this level the sim is about 1.6 times too optimistic: the real house bots are tougher.
- **Precision:** one 96-match batch can't separate differences smaller than about 0.5 sim points (≈ 0.3 real).
- **Free-for-all sim** (48 matches, expert house bots): GPT 12.0 vs this repo 12.12, a tie.
- **Tried and dropped (merge):** porting this repo's additions onto the GPT bot (`89ec1cd`). The additions were the watchdog, weapon-first with weapon memory, free-for-all detection with third-party kills, and juking.
  - Result: 5.66 (−0.61 ± 0.43 vs the GPT bot alone).
  - Also fighting only aggressors in practice: 5.60 (−0.67 ± 0.50).

## v5: free-for-all detection, third-party kills
- **Detection:** practice house bots never kill each other, so deaths the bot didn't cause (`mechs − alive − own kills`; one before 150 s, or two after) mean a free-for-all. It's then latched for the match; in one test it was detected at 12.6 s.
- **Third-party (free-for-all only):** join in on a non-hostile mech below 45% HP that lost HP to someone else in the last 4 s, within 120 m, while the bot is above 50% HP with at most one hostile on it.
- **Sim D** (sim B plus the real 130 m spawn spacing instead of 90 m; seeds 200–295): v4 practice 6.07 and free-for-all 12.00.
  - v1 (`30154ab`) on sim D: 4.14, so v1 → v5 is **+1.93 ± 0.48** (61 matches better, 28 worse).
- **v5 results:**
  - Practice: 6.06 (−0.01 ± 0.08; 89 of 96 matches identical, so it's off as intended).
  - Free-for-all: 12.12 (+0.12 ± 0.23). Docker check: PASS.
- **Seen in free-for-all traces:** early deaths come from being shot in the back (1.5× damage) by a second attacker outside the 120° field of view while dueling.

## v4: crash-proofing, react to being shot
- **Crash fix:** enemy fields the server may hide or send as null (HP when `vision.show_enemy_hp` is off, aim, velocity, cubes) now get neutral defaults. Before, a replay of the check stream with enemy HP hidden crashed `act()` every tick and left the mech coasting. Now: 0 errors.
- **Juke:** when the bot is standing still (cover, healing, holding) and gets hit, it strafes across the line of fire.
- **Cover:** if the bot is hit at its cover spot, it picks a new spot at once instead of waiting up to 0.7 s.
- **Shoot back:** targeting prefers hostiles in line of sight (one batched check), so the bot shoots back at whoever can be hit.
- **Sim B:** 5.36 → 5.39 (+0.02 ± 0.25), neutral. Kept because these are plainly the right reactions.
- **Free-for-all sim:** 11.85 vs 11.85 (48 matches, 15 expert house bots). Docker check: PASS.
- **Tried and dropped:** upgrade order (sim B, 96 matches). Nanites first: −0.10 ± 0.12, identical in 89 of 96 matches. Damage first: −0.19 ± 0.22. Plating first stays.
- **Free-for-all sim mode (`FFA=1`):** every house bot fights the nearest mech it can see within 150 m, preferring whoever hit it. `SKILL=expert` sets every house bot's tier. Against gun-only expert bots, the bot averages about 4th place. Its main loss is early deaths at spawn (9 of 48 within 30 s).

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
