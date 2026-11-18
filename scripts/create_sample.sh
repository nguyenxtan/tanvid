#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
mkdir -p data/samples
# Original synthetic content: no downloaded footage, music, or third-party assets.
# Do not overwrite an existing sample.
exec ffmpeg -nostdin -n -hide_banner -loglevel error \
    -f lavfi -i 'color=c=blue:s=320x240:r=25:d=2' \
    -f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=2' \
    -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 64k \
    -shortest -movflags +faststart data/samples/authorized-generated.mp4
