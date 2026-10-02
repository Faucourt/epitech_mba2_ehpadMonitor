#!/bin/sh
set -eu
cd "$(dirname "$0")/../chips"
for source in *.chip.c; do
  clang --target=wasm32-wasi --sysroot=/usr/share/wasi-sysroot -O2 -nostdlib \
    -Wl,--no-entry -Wl,--allow-undefined -Wl,--export=chipInit -Wl,--export-table \
    -Wl,--export=__wokwi_api_version_1 "$source" -lc -lm -o "${source%.chip.c}.wasm"
done
