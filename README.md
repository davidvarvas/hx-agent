# Mech Royale bot: team "404 Competition Not Found"

A bot for the Builders Buildathon **Mech Royale** track. It speaks `mechfight/1` JSON lines on stdin/stdout.

## Credit
`bot.py` is built on **[mech-royale by LanceHuang245](https://github.com/LanceHuang245/mech-royale)** (commit
`171bc06`, MIT License, Copyright (c) 2026 LanceHuang245). It is the strongest public entry we found, with 4.75 in
practice in this configuration (all strategy switches off). The license notice is in
`third_party/LanceHuang245-mech-royale-LICENSE`, and the credit is repeated at the top of `bot.py`. Every change we
make on top of it is listed in `CHANGELOG.md`. `mechfight.py` is the official kit's Python wrapper, unchanged.

## Files
| Path | What it is |
| --- | --- |
| `Dockerfile` | The image the scorer builds: pinned Python base, standard library only. |
| `bot.py` | The bot (see Credit). |
| `mechfight.py` | The kit's stdin/stdout wrapper. |
| `third_party/` | License notices for code we build on. |
| `tools/docker_check.sh` | Builds the image and runs the kit's check in the match sandbox, plus a linux/amd64 build. |
| `tools/sim.py`, `tools/batch.py` | A rough local simulator. It isn't the real game, and it has mis-ranked tactics. |
| `tools/live.py` | Plays one private match on the public play server (a free-for-all with the server's bots). |
| `nav.py` | Map model used by `tools/sim.py` only. It isn't in the image. |

## Check before submitting
```sh
tools/docker_check.sh        # needs Docker; the kit must sit next to this repo as ../mechfight-kit
```
