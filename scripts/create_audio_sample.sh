#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
OUTPUT=${1:-data/samples/authorized-180s.mp4}
mkdir -p "$(dirname -- "$OUTPUT")"
# Original generated color/tone, no external assets. Refuse overwrite.
exec ffmpeg -nostdin -n -hide_banner -loglevel error \
    -f lavfi -i 'color=c=green:s=160x120:r=10:d=180' \
    -f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=180' \
    -c:v libx264 -pix_fmt yuv420p -ac 2 -c:a aac -b:a 96k \
    -shortest -movflags +faststart "$OUTPUT"
