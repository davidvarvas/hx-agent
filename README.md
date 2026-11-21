# Mech Royale bot: team "404 Competition Not Found"

A bot for the Builders Buildathon **Mech Royale** track. It speaks `mechfight/1` JSON lines on stdin/stdout.

This is our team's own code. It is built from our original "survivor" bot and our own second version
(`davidvarvas/mech-royale-bot-gpt`). Every change is in `CHANGELOG.md`. `mechfight.py` is a compact stdin/stdout loop.

## Files
| Path | What it is |
| --- | --- |
| `Dockerfile` | The image the scorer builds: pinned Python base and pinned numpy. |
| `bot.py` | Decisions: zone, targets, fights, retreat, loot, upgrades, aiming. |
| `nav.py` | Map model: walk grid, line of sight, A* paths. |
| `mechfight.py` | stdin/stdout loop (answers only the newest observation). |
| `tools/docker_check.sh` | Builds the image and runs the kit's check in the match sandbox, plus a linux/amd64 build. |
| `tools/sim.py`, `tools/batch.py` | A rough local simulator. It isn't the real game, and it has mis-ranked tactics. |
| `tools/live.py` | Plays one private match on the public play server. |

## Check before submitting
```sh
tools/docker_check.sh        # needs Docker; the kit must sit next to this repo as ../mechfight-kit
```
