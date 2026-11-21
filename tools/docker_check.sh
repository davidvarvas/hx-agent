#!/bin/sh
# Pre-submission check: build the image and run the kit's conformance check exactly as the README does
# (the match sandbox: no network, 1 CPU, 512 MB, read-only disk except /tmp, uid 65534, map at /arena),
# then confirm the image also builds for linux/amd64, the scorer's platform.
#   tools/docker_check.sh [path-to-kit]        (default: ../mechfight-kit)
set -e
cd "$(dirname "$0")/.."
KIT="${1:-../mechfight-kit}"
docker build -q -t mech-royale-bot . >/dev/null
(cd "$KIT" && python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m \
    --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" mech-royale-bot)
docker buildx build --platform linux/amd64 -q --load -t mech-royale-bot:amd64 . >/dev/null
echo "linux/amd64 build: OK"
